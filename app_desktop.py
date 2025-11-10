import sys, os, json
from datetime import datetime
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton,
    QLineEdit, QLabel, QTextEdit, QHBoxLayout, QSpinBox, QComboBox,
    QGroupBox, QFrame, QSplitter, QTabWidget, QTableWidget, 
    QTableWidgetItem, QProgressBar, QCheckBox, QDoubleSpinBox, 
    QMessageBox, QFileDialog, QInputDialog
)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtCore import QUrl, pyqtSlot, QObject, pyqtSignal, Qt, QThread
from PyQt6.QtGui import QFont, QPalette, QColor
import folium
from folium import plugins
from geopy.geocoders import Nominatim

# import your framework modules
from modules.network_builder import generate_network_from_bbox
from modules.demand_generator import generate_routes, generate_targeted_routes
from modules.simulator import create_config, run_simulation
from modules.database import get_db
from modules.data_collector import TrafficDataCollector, TrafficDataAnalyzer
from modules.area_comparison import AreaBasedComparison
from modules.ai_predictor import SimpleTrafficPredictor, AdaptivePredictor
from modules.area_manager import AreaManager
from modules.area_wide_collector import AreaWideCollector
from modules.simple_route_generator import SimpleRouteGenerator


# ============== WORKER THREADS ==============

class DataCollectionWorker(QThread):
    """Background thread for data collection"""
    progress = pyqtSignal(str)
    finished = pyqtSignal(dict)
    
    def __init__(self, api_key, route_ids=None):
        super().__init__()
        self.api_key = api_key
        self.route_ids = route_ids
        self.running = True
    
    def run(self):
        try:
            collector = TrafficDataCollector(self.api_key)
            self.progress.emit("Collecting real-world traffic data...")
            results = collector.collect_all_probe_routes()
            self.progress.emit(f"Collected data for {len(results)} routes")
            self.finished.emit(results)
        except Exception as e:
            self.progress.emit(f"Error: {str(e)}")
            self.finished.emit({})

class SimulationWorker(QThread):
    """Background thread for simulation"""
    progress = pyqtSignal(str)
    finished = pyqtSignal(str)

    def __init__(self, cfg_file, scenario_id):
        super().__init__()
        self.cfg_file = cfg_file
        self.scenario_id = scenario_id

    def run(self):
        try:
            self.progress.emit("Running simulation...")

            # Get Cairo traffic parameters for realistic simulation
            from modules.traffic_configurator import TrafficConfigurator
            configurator = TrafficConfigurator()
            cairo_params = configurator.configure_cairo_parameters(avg_speed_kmh=40.0)

            run_simulation(
                self.cfg_file,
                gui=False,
                scenario_id=self.scenario_id,
                enable_dynamic_calibration=True,
                initial_params=cairo_params
            )
            self.progress.emit("Simulation complete!")
            self.finished.emit(self.scenario_id)
        except Exception as e:
            self.progress.emit(f"Error: {str(e)}")
            self.finished.emit("")

class ScheduledCollectionWorker(QThread):
    """Background thread for scheduled data collection"""
    progress = pyqtSignal(str)
    collection_complete = pyqtSignal(int, int)  # (current, total)
    finished = pyqtSignal()

    def __init__(self, api_key, route_ids, interval_minutes, duration_hours):
        super().__init__()
        self.api_key = api_key
        self.route_ids = route_ids
        self.interval_minutes = interval_minutes
        self.duration_hours = duration_hours
        self.running = True

    def run(self):
        import time
        try:
            collector = TrafficDataCollector(self.api_key)
            start_time = time.time()
            collection_count = 0

            # Calculate total collections
            total_collections = int((self.duration_hours * 60) / self.interval_minutes)

            self.progress.emit(f"Starting scheduled collection for {self.duration_hours} hours...")

            while self.running:
                collection_count += 1

                # Collect data for all routes
                self.progress.emit(f"Collection #{collection_count}/{total_collections}...")
                results = collector.collect_all_probe_routes()
                self.progress.emit(f"✅ Collected data for {len(results)} routes")

                # Emit progress
                self.collection_complete.emit(collection_count, total_collections)

                # Check if we should stop
                elapsed_hours = (time.time() - start_time) / 3600
                if elapsed_hours >= self.duration_hours:
                    self.progress.emit(f"✅ Completed {self.duration_hours} hours of collection!")
                    break

                # Wait for next collection
                if self.running:
                    self.progress.emit(f"Waiting {self.interval_minutes} minutes...")
                    for _ in range(self.interval_minutes * 60):
                        if not self.running:
                            break
                        time.sleep(1)

            self.progress.emit("Collection stopped")
            self.finished.emit()

        except Exception as e:
            self.progress.emit(f"Error: {str(e)}")
            self.finished.emit()

    def stop(self):
        """Stop the collection"""
        self.running = False

class AreaTrainingWorker(QThread):
    """Background thread for area-wide training data collection"""
    progress = pyqtSignal(str)
    collection_update = pyqtSignal(int, int, dict)  # (current, total, snapshot_data)
    finished = pyqtSignal()

    def __init__(self, api_key, area_id, duration_days, interval_minutes=15, grid_size=5):
        super().__init__()
        self.api_key = api_key
        self.area_id = area_id
        self.duration_days = duration_days
        self.interval_minutes = interval_minutes
        self.grid_size = grid_size
        self.running = True

    def run(self):
        try:
            # Initialize collector
            collector = AreaWideCollector(self.api_key, self.area_id, grid_size=self.grid_size)

            # Progress callback
            def progress_callback(current, total, snapshot):
                if self.running:
                    self.collection_update.emit(current, total, snapshot)
                    self.progress.emit(f"Collection {current}/{total} complete")

            # Start collection
            self.progress.emit(f"Starting {self.duration_days}-day training data collection...")
            collector.collect_training_data(
                duration_days=self.duration_days,
                interval_minutes=self.interval_minutes,
                progress_callback=progress_callback
            )

            if self.running:
                self.progress.emit("Training data collection completed!")
            else:
                self.progress.emit("Training data collection stopped by user")

            self.finished.emit()

        except Exception as e:
            self.progress.emit(f"Error: {str(e)}")
            self.finished.emit()

    def stop(self):
        """Stop the collection"""
        self.running = False

class MapBridge(QObject):
    """Bridge for JavaScript to Python communication"""
    regionSelected = pyqtSignal(str)  # emits JSON coords

    @pyqtSlot(str)
    def receiveRegion(self, data):
        print(f"[BRIDGE] receiveRegion called with: {data}")
        self.regionSelected.emit(data)
        print(f"[BRIDGE] Signal emitted")

class RouteBridge(QObject):
    """Bridge for route point selection (JavaScript to Python)"""
    pointSelected = pyqtSignal(float, float)  # emits lat, lon

    @pyqtSlot(float, float)
    def receivePoint(self, lat, lon):
        print(f"[ROUTE_BRIDGE] Point selected: {lat}, {lon}")
        self.pointSelected.emit(lat, lon)

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🚦 Digital Twin Traffic Simulator - Complete System")
        self.resize(1600, 1000)
        
        # Initialize database and API
        self.db = get_db()
        self.api_key = self.load_api_key()

        # Initialize area manager
        self.area_manager = AreaManager()
        self.area_training_worker = None
        self.current_area_id = None

        # Map and simulation state (ORIGINAL)
        self.map_file = "map.html"
        self.area_map_file = "area_map.html"
        self.selected_bbox = None
        self.selected_network_file = None  # Track selected cached network file
        self.area_selected_bbox = None  # Separate bbox for area training tab
        self.current_location = None
        
        # Setup UI with tabs
        self.setup_ui()
        self.apply_styles()
        
        # Initialize map (ORIGINAL)
        self.bridge = MapBridge()
        self.channel = QWebChannel()
        self.channel.registerObject("bridge", self.bridge)
        self.view.page().setWebChannel(self.channel)
        self.bridge.regionSelected.connect(self.on_region_selected)
        self.view.loadFinished.connect(self.on_map_loaded)
        self.init_map([30.0444, 31.2357], 12)

        print("[DEBUG] Bridge and channel initialized")

        # Initialize area training map
        self.area_bridge = MapBridge()
        self.area_channel = QWebChannel()
        self.area_channel.registerObject("bridge", self.area_bridge)
        self.area_map_view.page().setWebChannel(self.area_channel)
        self.area_bridge.regionSelected.connect(self.on_area_region_selected)
        self.area_map_view.loadFinished.connect(self.on_area_map_loaded)
        self.init_area_map([30.0444, 31.2357], 12)

        print("[DEBUG] Area training bridge and channel initialized")

        # Initialize route estimation map
        try:
            self.route_bridge = RouteBridge()
            self.route_channel = QWebChannel()
            self.route_channel.registerObject("bridge", self.route_bridge)

            # Enable web console messages for debugging
            self.route_map_view.page().javaScriptConsoleMessage = lambda level, message, lineNumber, sourceID: print(f"[ROUTE_MAP JS] {message}")

            self.route_map_view.page().setWebChannel(self.route_channel)
            self.route_bridge.pointSelected.connect(self.on_route_point_selected)
            self.route_map_view.loadFinished.connect(self.on_route_map_loaded)

            print(f"[DEBUG] Route map view exists: {self.route_map_view is not None}")
            print(f"[DEBUG] Initializing route map...")
            self.init_route_map()  # Use default parameters
            print("[DEBUG] Route estimation bridge and channel initialized")
        except Exception as e:
            print(f"[ERROR] Failed to initialize route map: {e}")
            import traceback
            traceback.print_exc()

        # Load initial dashboard data
        self.refresh_dashboard()

    def load_api_key(self):
        """Load API key from .env file"""
        try:
            with open('.env', 'r') as f:
                for line in f:
                    if line.startswith('GOOGLE_MAPS_API_KEY='):
                        return line.split('=', 1)[1].strip()
        except:
            pass
        return None

    def setup_ui(self):
        """Setup the user interface with tabs"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # ===== HEADER =====
        header = QLabel("🌍 Digital Twin Traffic Simulator - Complete Control Center")
        header.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(header)

        subtitle = QLabel("Integrated map simulation, digital twin dashboard, calibration, AI prediction & analysis")
        subtitle.setFont(QFont("Segoe UI", 10))
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(subtitle)

        # ===== TAB WIDGET =====
        self.tabs = QTabWidget()
        self.tabs.setFont(QFont("Segoe UI", 10))
        
        # Tab 1: Map & Simulation (ORIGINAL FUNCTIONALITY)
        self.tab_simulation = self.create_simulation_tab()
        self.tabs.addTab(self.tab_simulation, "🗺️ Map & Simulation")
        
        # Tab 2: Route Selection (NEW - 5 PRIMARY ROUTES)
        self.tab_routes = self.create_route_selection_tab()
        self.tabs.addTab(self.tab_routes, "🛣️ Route Selection (5 Routes)")

        # Tab 3: Area Training (NEW - AREA-BASED WORKFLOW)
        self.tab_area_training = self.create_area_training_tab()
        self.tabs.addTab(self.tab_area_training, "🌐 Area Training")

        # Tab 4: Digital Twin Dashboard (NEW)
        self.tab_dashboard = self.create_dashboard_tab()
        self.tabs.addTab(self.tab_dashboard, "📊 Digital Twin Dashboard")

        # Tab 5: Calibration Center (NEW)
        self.tab_calibration = self.create_calibration_tab()
        self.tabs.addTab(self.tab_calibration, "🔧 Calibration Center")

        # Tab 6: AI Prediction (NEW)
        self.tab_ai = self.create_ai_tab()
        self.tabs.addTab(self.tab_ai, "🤖 AI Prediction")

        # Tab 7: Results & Analysis (NEW)
        self.tab_results = self.create_results_tab()
        self.tabs.addTab(self.tab_results, "📈 Results & Analysis")
        
        main_layout.addWidget(self.tabs)
        
        # Status bar
        self.status_label = QLabel("Ready")
        self.status_label.setFont(QFont("Segoe UI", 9))
        main_layout.addWidget(self.status_label)

    def manually_regenerate_routes(self):
        """Allow user to customize route generation"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QComboBox, QSpinBox, QDialogButtonBox
        
        if not self.selected_bbox:
            return
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Route Generation Options")
        layout = QVBoxLayout(dialog)
        
        # Strategy
        layout.addWidget(QLabel("Strategy:"))
        strategy_combo = QComboBox()
        strategy_combo.addItems(['grid', 'radial', 'loop', 'mixed'])
        layout.addWidget(strategy_combo)
        
        # Number
        layout.addWidget(QLabel("Number of routes:"))
        num_spin = QSpinBox()
        num_spin.setRange(3, 15)
        num_spin.setValue(8)
        layout.addWidget(num_spin)
        
        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            QMessageBox.information(self, "Info",
                "Routes will be automatically generated from network topology during simulation!")

    # ============== TAB 1: MAP & SIMULATION (ORIGINAL - UNTOUCHED) ==============
    
    def create_simulation_tab(self):
        """Create the original map and simulation tab - EXACT COPY"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # ===== SEARCH SECTION =====
        search_group = QGroupBox("🔍 Location Search")
        search_group.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        search_layout = QHBoxLayout(search_group)

        self.location_input = QLineEdit()
        self.location_input.setPlaceholderText("Enter location (e.g., Berlin, Germany or New York, USA)")
        self.location_input.setMinimumHeight(40)
        self.location_input.setFont(QFont("Segoe UI", 10))
        self.location_input.returnPressed.connect(self.on_search)

        self.search_btn = QPushButton("🔍 Search Location")
        self.search_btn.setMinimumHeight(40)
        self.search_btn.setMinimumWidth(150)
        self.search_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self.search_btn.clicked.connect(self.on_search)

        search_layout.addWidget(self.location_input, 1)
        search_layout.addWidget(self.search_btn)
        layout.addWidget(search_group)

        # ===== MAP SECTION =====
        map_group = QGroupBox("🗺️ Interactive Map - Draw a rectangle to select simulation area")
        map_group.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        map_layout = QVBoxLayout(map_group)

        # Map instructions
        instructions = QLabel("💡 Tip: Use the rectangle tool (▢) on the left side of the map to select your desired area")
        instructions.setFont(QFont("Segoe UI", 9))
        instructions.setStyleSheet("color: #666; padding: 5px;")
        map_layout.addWidget(instructions)

        self.view = QWebEngineView()
        self.view.setMinimumHeight(400)

        # Enable developer tools and better error handling
        from PyQt6.QtWebEngineCore import QWebEngineSettings
        settings = self.view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.ErrorPageEnabled, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)

        # Connect console messages for debugging
        self.view.page().javaScriptConsoleMessage = self.handle_js_console_message

        map_layout.addWidget(self.view, 1)

        # Selection status - CREATE LAYOUT FIRST!
        selection_layout = QHBoxLayout()  # ← Create FIRST
        
        self.selection_label = QLabel("📌 No area selected")
        self.selection_label.setFont(QFont("Segoe UI", 10))
        
        self.clear_btn = QPushButton("🗑️ Clear Selection")
        self.clear_btn.setEnabled(False)
        self.clear_btn.setMinimumHeight(35)
        self.clear_btn.clicked.connect(self.on_clear_selection)
        
        # Add to layout
        selection_layout.addWidget(self.selection_label, 1)
        selection_layout.addWidget(self.clear_btn)
        
        # Optional: Add regenerate button (now it works!)
        # Uncomment these lines if you want the button:
        # self.regenerate_routes_btn = QPushButton("🔄 Regenerate Routes")
        # self.regenerate_routes_btn.setEnabled(False)
        # self.regenerate_routes_btn.setMinimumHeight(35)
        # self.regenerate_routes_btn.clicked.connect(self.manually_regenerate_routes)
        # selection_layout.addWidget(self.regenerate_routes_btn)
        
        map_layout.addLayout(selection_layout)
        selection_layout.addWidget(self.selection_label, 1)
        selection_layout.addWidget(self.clear_btn)
        map_layout.addLayout(selection_layout)

        layout.addWidget(map_group, 2)

        # ===== SIMULATION CONTROLS =====
        controls_group = QGroupBox("⚙️ Simulation Parameters")
        controls_group.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        controls_layout = QHBoxLayout(controls_group)

        # Duration
        dur_label = QLabel("⏱️ Duration (seconds):")
        dur_label.setFont(QFont("Segoe UI", 10))
        self.duration = QSpinBox()
        self.duration.setRange(300, 14400)  # Extended to 4 hours max
        self.duration.setValue(7200)  # Default 2 hours for better data coverage
        self.duration.setSuffix(" s")
        self.duration.setMinimumHeight(35)
        self.duration.setMinimumWidth(120)
        self.duration.setFont(QFont("Segoe UI", 10))

        # Traffic intensity
        traffic_label = QLabel("🚗 Traffic Intensity:")
        traffic_label.setFont(QFont("Segoe UI", 10))
        self.intensity = QComboBox()
        self.intensity.addItems(["Low", "Medium", "High"])
        self.intensity.setCurrentIndex(1)
        self.intensity.setMinimumHeight(35)
        self.intensity.setMinimumWidth(120)
        self.intensity.setFont(QFont("Segoe UI", 10))

        controls_layout.addWidget(dur_label)
        controls_layout.addWidget(self.duration)
        controls_layout.addSpacing(20)
        controls_layout.addWidget(traffic_label)
        controls_layout.addWidget(self.intensity)
        controls_layout.addSpacing(20)

        # Dynamic Calibration indicator
        calib_indicator = QLabel("🎯 Dynamic Calibration: ENABLED")
        calib_indicator.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        calib_indicator.setStyleSheet("color: #4CAF50; padding: 5px; background: #E8F5E9; border-radius: 5px;")
        controls_layout.addWidget(calib_indicator)

        controls_layout.addStretch()

        # View cached networks button
        self.view_cache_btn = QPushButton("💾 View Cached Networks")
        self.view_cache_btn.setMinimumHeight(40)
        self.view_cache_btn.setFont(QFont("Segoe UI", 10))
        self.view_cache_btn.clicked.connect(self.view_cached_networks)
        controls_layout.addWidget(self.view_cache_btn)

        # Run button
        self.run_btn = QPushButton("▶️ Run Simulation")
        self.run_btn.setMinimumHeight(45)
        self.run_btn.setMinimumWidth(180)
        self.run_btn.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
        self.run_btn.clicked.connect(self.on_run)
        controls_layout.addWidget(self.run_btn)

        layout.addWidget(controls_group)

        # ===== CONSOLE OUTPUT =====
        console_group = QGroupBox("📋 Console Output")
        console_group.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        console_layout = QVBoxLayout(console_group)

        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setFont(QFont("Consolas", 9))
        self.console.setMinimumHeight(150)
        console_layout.addWidget(self.console)

        layout.addWidget(console_group, 1)

        return tab

    # ============== TAB 2: ROUTE SELECTION (5 PRIMARY ROUTES) ==============

    def create_route_selection_tab(self):
        """Create tab for selecting 5 specific routes for congestion prediction"""
        from PyQt6.QtWidgets import QScrollArea

        tab = QWidget()
        main_layout = QVBoxLayout(tab)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Create scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Container widget for scrollable content
        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Info section
        info_label = QLabel(
            "🛣️ Define 5 specific routes for congestion prediction\n"
            "Enter location names (e.g., 'Cairo Airport', 'Tahrir Square') and we'll find coordinates automatically!"
        )
        info_label.setWordWrap(True)
        info_label.setFont(QFont("Segoe UI", 10))
        info_label.setStyleSheet("background-color: #e3f2fd; padding: 10px; border-radius: 5px;")
        layout.addWidget(info_label)

        # Container for 5 route cards
        self.route_cards = []
        for i in range(5):
            card = self.create_route_card(i + 1)
            layout.addWidget(card)
            self.route_cards.append(card)

        # Scheduled Data Collection Section
        collection_group = QGroupBox("⏰ Scheduled Data Collection")
        collection_group.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        collection_layout = QVBoxLayout(collection_group)

        # Collection interval
        interval_layout = QHBoxLayout()
        interval_layout.addWidget(QLabel("Collection Interval:"))
        self.collection_interval_spin = QSpinBox()
        self.collection_interval_spin.setRange(5, 120)
        self.collection_interval_spin.setValue(15)
        self.collection_interval_spin.setSuffix(" minutes")
        interval_layout.addWidget(self.collection_interval_spin)
        interval_layout.addStretch()
        collection_layout.addLayout(interval_layout)

        # Collection duration
        duration_layout = QHBoxLayout()
        duration_layout.addWidget(QLabel("Collection Duration:"))
        self.collection_duration_spin = QSpinBox()
        self.collection_duration_spin.setRange(1, 168)
        self.collection_duration_spin.setValue(24)
        self.collection_duration_spin.setSuffix(" hours")
        duration_layout.addWidget(self.collection_duration_spin)
        duration_layout.addStretch()
        collection_layout.addLayout(duration_layout)

        # Collection status
        self.collection_status_label = QLabel("Status: ⚪ Not running")
        self.collection_status_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        collection_layout.addWidget(self.collection_status_label)

        # Collection progress
        self.collection_progress_bar = QProgressBar()
        self.collection_progress_bar.setValue(0)
        collection_layout.addWidget(self.collection_progress_bar)

        # Collection buttons
        collection_btn_layout = QHBoxLayout()
        self.start_scheduled_btn = QPushButton("▶️ Start Scheduled Collection")
        self.start_scheduled_btn.clicked.connect(self.start_scheduled_collection)
        self.start_scheduled_btn.setStyleSheet("background-color: #4CAF50; padding: 8px;")
        collection_btn_layout.addWidget(self.start_scheduled_btn)

        self.stop_scheduled_btn = QPushButton("⏹️ Stop Collection")
        self.stop_scheduled_btn.clicked.connect(self.stop_scheduled_collection)
        self.stop_scheduled_btn.setEnabled(False)
        self.stop_scheduled_btn.setStyleSheet("background-color: #f44336; padding: 8px;")
        collection_btn_layout.addWidget(self.stop_scheduled_btn)
        collection_layout.addLayout(collection_btn_layout)

        layout.addWidget(collection_group)

        # Action buttons at bottom
        actions_layout = QHBoxLayout()

        self.load_routes_btn = QPushButton("📂 Load Saved Routes")
        self.load_routes_btn.clicked.connect(self.load_primary_routes)
        actions_layout.addWidget(self.load_routes_btn)

        self.collect_now_btn = QPushButton("📊 Collect Data Now (All 5 Routes)")
        self.collect_now_btn.clicked.connect(self.collect_data_from_5_routes)
        self.collect_now_btn.setStyleSheet("background-color: #2196F3; padding: 8px;")
        actions_layout.addWidget(self.collect_now_btn)

        actions_layout.addStretch()
        layout.addLayout(actions_layout)

        layout.addStretch()

        # Set the scroll content
        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll)

        # Initialize scheduled collection worker
        self.scheduled_worker = None

        return tab

    def create_route_card(self, route_num):
        """Create a card for one route"""
        card = QGroupBox(f"🛣️ Route {route_num}")
        card.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        card_layout = QVBoxLayout(card)

        # Route name
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Route Name:"))
        route_name_input = QLineEdit()
        route_name_input.setPlaceholderText(f"e.g., Downtown to Airport")
        route_name_input.setObjectName(f"route_name_{route_num}")
        name_layout.addWidget(route_name_input)
        card_layout.addLayout(name_layout)

        # Origin location name
        origin_layout = QHBoxLayout()
        origin_layout.addWidget(QLabel("Origin Location:"))
        origin_input = QLineEdit()
        origin_input.setPlaceholderText("e.g., Cairo Airport, Tahrir Square")
        origin_input.setObjectName(f"origin_location_{route_num}")
        origin_layout.addWidget(origin_input)

        origin_search_btn = QPushButton("🔍")
        origin_search_btn.setMaximumWidth(40)
        origin_search_btn.setToolTip("Find coordinates")
        origin_search_btn.clicked.connect(lambda checked, num=route_num: self.geocode_origin(num))
        origin_layout.addWidget(origin_search_btn)
        card_layout.addLayout(origin_layout)

        # Destination location name
        dest_layout = QHBoxLayout()
        dest_layout.addWidget(QLabel("Destination Location:"))
        dest_input = QLineEdit()
        dest_input.setPlaceholderText("e.g., New Cairo, Giza Pyramids")
        dest_input.setObjectName(f"dest_location_{route_num}")
        dest_layout.addWidget(dest_input)

        dest_search_btn = QPushButton("🔍")
        dest_search_btn.setMaximumWidth(40)
        dest_search_btn.setToolTip("Find coordinates")
        dest_search_btn.clicked.connect(lambda checked, num=route_num: self.geocode_destination(num))
        dest_layout.addWidget(dest_search_btn)
        card_layout.addLayout(dest_layout)

        # Coordinates display (read-only, filled by geocoding)
        coords_layout = QHBoxLayout()
        coords_label = QLabel("Coordinates:")
        coords_label.setStyleSheet("font-size: 9pt; color: #666;")
        coords_layout.addWidget(coords_label)

        coords_display = QLabel("Not set")
        coords_display.setObjectName(f"coords_display_{route_num}")
        coords_display.setStyleSheet("font-size: 9pt; color: #666;")
        coords_display.setWordWrap(True)
        coords_layout.addWidget(coords_display, 1)
        card_layout.addLayout(coords_layout)

        # Hidden coordinate fields (for actual storage)
        origin_lat_input = QDoubleSpinBox()
        origin_lat_input.setRange(-90, 90)
        origin_lat_input.setDecimals(6)
        origin_lat_input.setValue(30.0444)
        origin_lat_input.setObjectName(f"origin_lat_{route_num}")
        origin_lat_input.setVisible(False)

        origin_lon_input = QDoubleSpinBox()
        origin_lon_input.setRange(-180, 180)
        origin_lon_input.setDecimals(6)
        origin_lon_input.setValue(31.2357)
        origin_lon_input.setObjectName(f"origin_lon_{route_num}")
        origin_lon_input.setVisible(False)

        dest_lat_input = QDoubleSpinBox()
        dest_lat_input.setRange(-90, 90)
        dest_lat_input.setDecimals(6)
        dest_lat_input.setValue(30.0644)
        dest_lat_input.setObjectName(f"dest_lat_{route_num}")
        dest_lat_input.setVisible(False)

        dest_lon_input = QDoubleSpinBox()
        dest_lon_input.setRange(-180, 180)
        dest_lon_input.setDecimals(6)
        dest_lon_input.setValue(31.2557)
        dest_lon_input.setObjectName(f"dest_lon_{route_num}")
        dest_lon_input.setVisible(False)

        card_layout.addWidget(origin_lat_input)
        card_layout.addWidget(origin_lon_input)
        card_layout.addWidget(dest_lat_input)
        card_layout.addWidget(dest_lon_input)

        # Action buttons for this route
        btn_layout = QHBoxLayout()

        save_btn = QPushButton(f"💾 Save")
        save_btn.clicked.connect(lambda checked, num=route_num: self.save_route(num))
        btn_layout.addWidget(save_btn)

        collect_btn = QPushButton(f"📊 Collect")
        collect_btn.clicked.connect(lambda checked, num=route_num: self.collect_route_data(num))
        btn_layout.addWidget(collect_btn)

        view_btn = QPushButton(f"🗺️ Map")
        view_btn.clicked.connect(lambda checked, num=route_num: self.view_route_on_map(num))
        btn_layout.addWidget(view_btn)

        btn_layout.addStretch()
        card_layout.addLayout(btn_layout)

        # Status label
        status_label = QLabel("⚪ Not configured")
        status_label.setObjectName(f"status_{route_num}")
        card_layout.addWidget(status_label)

        return card

    # ============== TAB 3: AREA TRAINING ==============

    def create_area_training_tab(self):
        """Create area training tab for area-based workflow"""
        from PyQt6.QtWidgets import QScrollArea

        tab = QWidget()
        main_layout = QVBoxLayout(tab)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Create scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Container widget for scrollable content
        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Info section
        info_label = QLabel(
            "🌐 Area-Based Training Workflow\n"
            "1. Select a fixed area on the map (Tab 1)\n"
            "2. Create a monitored area with SUMO network\n"
            "3. Collect training data for weeks/months\n"
            "4. Pick ANY 5 routes within the area for prediction"
        )
        info_label.setWordWrap(True)
        info_label.setFont(QFont("Segoe UI", 10))
        info_label.setStyleSheet("background-color: #e3f2fd; padding: 15px; border-radius: 5px;")
        layout.addWidget(info_label)

        # Step 1: Area Creation
        area_create_group = QGroupBox("Step 1: Create Monitored Area")
        area_create_group.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        area_create_layout = QVBoxLayout(area_create_group)

        # Area name
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Area Name:"))
        self.area_name_input = QLineEdit()
        self.area_name_input.setPlaceholderText("e.g., Downtown Cairo, New Cairo District")
        name_layout.addWidget(self.area_name_input)
        area_create_layout.addLayout(name_layout)

        # Grid size for sampling
        grid_layout = QHBoxLayout()
        grid_layout.addWidget(QLabel("Sampling Grid Size:"))
        self.grid_size_spin = QSpinBox()
        self.grid_size_spin.setRange(3, 10)
        self.grid_size_spin.setValue(5)
        self.grid_size_spin.setToolTip("NxN grid for area sampling. 5x5 = 25 points, 40 routes")
        grid_layout.addWidget(self.grid_size_spin)
        grid_layout.addWidget(QLabel("x"))
        self.grid_size_label = QLabel("5 (25 points, 40 routes)")
        self.grid_size_spin.valueChanged.connect(self.update_grid_info)
        grid_layout.addWidget(self.grid_size_label)
        grid_layout.addStretch()
        area_create_layout.addLayout(grid_layout)

        # Build network checkbox
        self.build_network_check = QCheckBox("Build SUMO network from OpenStreetMap")
        self.build_network_check.setChecked(True)
        area_create_layout.addWidget(self.build_network_check)

        # Map selector section
        map_selector_label = QLabel("Select area on map:")
        map_selector_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        area_create_layout.addWidget(map_selector_label)

        # Map instructions
        map_instructions = QLabel("Use the rectangle tool (▢) on the left side of the map to select your desired area")
        map_instructions.setFont(QFont("Segoe UI", 9))
        map_instructions.setStyleSheet("color: #666; padding: 5px;")
        area_create_layout.addWidget(map_instructions)

        # Create map view for area training
        self.area_map_view = QWebEngineView()
        self.area_map_view.setMinimumHeight(400)

        # Enable settings
        from PyQt6.QtWebEngineCore import QWebEngineSettings
        area_settings = self.area_map_view.settings()
        area_settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        area_settings.setAttribute(QWebEngineSettings.WebAttribute.ErrorPageEnabled, True)
        area_settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)

        # Connect console messages for debugging
        self.area_map_view.page().javaScriptConsoleMessage = self.handle_js_console_message

        area_create_layout.addWidget(self.area_map_view)

        # Current selection status
        self.area_bbox_label = QLabel("No area selected")
        self.area_bbox_label.setStyleSheet("color: #666; font-style: italic;")
        area_create_layout.addWidget(self.area_bbox_label)

        # Create area button
        create_area_btn_layout = QHBoxLayout()
        self.create_area_btn = QPushButton("Create Monitored Area")
        self.create_area_btn.clicked.connect(self.create_monitored_area)
        self.create_area_btn.setStyleSheet("background-color: #4CAF50; padding: 10px;")
        create_area_btn_layout.addWidget(self.create_area_btn)

        self.load_area_btn = QPushButton("Load Existing Area")
        self.load_area_btn.clicked.connect(self.load_existing_area)
        create_area_btn_layout.addWidget(self.load_area_btn)
        create_area_btn_layout.addStretch()

        area_create_layout.addLayout(create_area_btn_layout)

        layout.addWidget(area_create_group)

        # Step 2: Training Data Collection
        training_group = QGroupBox("Step 2: Collect Training Data")
        training_group.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        training_layout = QVBoxLayout(training_group)

        # Current area info
        self.training_area_info = QLabel("No area selected")
        self.training_area_info.setStyleSheet("font-weight: bold; color: #666;")
        training_layout.addWidget(self.training_area_info)

        # Training duration with flexible units
        duration_layout = QHBoxLayout()
        duration_layout.addWidget(QLabel("Training Duration:"))

        self.training_duration_spin = QSpinBox()
        self.training_duration_spin.setRange(1, 1000)
        self.training_duration_spin.setValue(2)
        self.training_duration_spin.setMinimumWidth(80)
        duration_layout.addWidget(self.training_duration_spin)

        self.training_duration_unit = QComboBox()
        self.training_duration_unit.addItems(["Minutes", "Hours", "Days", "Weeks"])
        self.training_duration_unit.setCurrentText("Weeks")
        self.training_duration_unit.setMinimumWidth(100)
        duration_layout.addWidget(self.training_duration_unit)

        duration_layout.addSpacing(20)
        duration_layout.addWidget(QLabel("Collection Interval:"))

        self.training_interval_spin = QSpinBox()
        self.training_interval_spin.setRange(1, 1000)
        self.training_interval_spin.setValue(15)
        self.training_interval_spin.setMinimumWidth(80)
        duration_layout.addWidget(self.training_interval_spin)

        self.training_interval_unit = QComboBox()
        self.training_interval_unit.addItems(["Minutes", "Hours"])
        self.training_interval_unit.setCurrentText("Minutes")
        self.training_interval_unit.setMinimumWidth(100)
        duration_layout.addWidget(self.training_interval_unit)

        duration_layout.addStretch()
        training_layout.addLayout(duration_layout)

        # Expected collections info
        self.collections_info_label = QLabel("")
        self.collections_info_label.setStyleSheet("color: #666; font-size: 9pt;")
        self.training_duration_spin.valueChanged.connect(self.update_collections_info)
        self.training_duration_unit.currentTextChanged.connect(self.update_collections_info)
        self.training_interval_spin.valueChanged.connect(self.update_collections_info)
        self.training_interval_unit.currentTextChanged.connect(self.update_collections_info)
        training_layout.addWidget(self.collections_info_label)
        self.update_collections_info()

        # Training controls
        training_btn_layout = QHBoxLayout()
        self.start_training_btn = QPushButton("Start Training Data Collection")
        self.start_training_btn.clicked.connect(self.start_area_training)
        self.start_training_btn.setEnabled(False)
        self.start_training_btn.setStyleSheet("background-color: #4CAF50; padding: 10px;")
        training_btn_layout.addWidget(self.start_training_btn)

        self.stop_training_btn = QPushButton("Stop Collection")
        self.stop_training_btn.clicked.connect(self.stop_area_training)
        self.stop_training_btn.setEnabled(False)
        self.stop_training_btn.setStyleSheet("background-color: #f44336; padding: 10px;")
        training_btn_layout.addWidget(self.stop_training_btn)
        training_btn_layout.addStretch()
        training_layout.addLayout(training_btn_layout)

        # Progress
        self.training_progress_bar = QProgressBar()
        self.training_progress_bar.setValue(0)
        training_layout.addWidget(self.training_progress_bar)

        self.training_status_label = QLabel("Status: Ready")
        self.training_status_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        training_layout.addWidget(self.training_status_label)

        # Latest snapshot info
        self.snapshot_info_label = QLabel("")
        self.snapshot_info_label.setStyleSheet("color: #666; font-size: 9pt;")
        training_layout.addWidget(self.snapshot_info_label)

        layout.addWidget(training_group)

        # Step 3: Area Status & Statistics
        status_group = QGroupBox("Step 3: Area Status & Statistics")
        status_group.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        status_layout = QVBoxLayout(status_group)

        # Statistics table
        self.area_stats_table = QTableWidget()
        self.area_stats_table.setColumnCount(2)
        self.area_stats_table.setHorizontalHeaderLabels(["Metric", "Value"])
        self.area_stats_table.horizontalHeader().setStretchLastSection(True)
        self.area_stats_table.setMaximumHeight(200)
        status_layout.addWidget(self.area_stats_table)

        # Refresh button
        refresh_btn = QPushButton("Refresh Statistics")
        refresh_btn.clicked.connect(self.refresh_area_stats)
        status_layout.addWidget(refresh_btn)

        layout.addWidget(status_group)

        layout.addStretch()

        # Set the scroll content
        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll)

        return tab

    # ============== TAB 4: DIGITAL TWIN DASHBOARD ==============

    def create_dashboard_tab(self):
        """Create digital twin dashboard"""
        from PyQt6.QtWidgets import QScrollArea

        tab = QWidget()
        main_layout = QVBoxLayout(tab)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Create scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Container widget for scrollable content
        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Data collection section
        collection_group = QGroupBox("📡 Real-World Data Collection")
        collection_layout = QVBoxLayout(collection_group)
        
        # API key status
        api_status_layout = QHBoxLayout()
        self.api_status_label = QLabel("API Key: " + ("✅ Configured" if self.api_key else "❌ Not configured"))
        api_status_layout.addWidget(self.api_status_label)
        
        self.config_api_btn = QPushButton("⚙️ Configure API Key")
        self.config_api_btn.clicked.connect(self.configure_api_key)
        api_status_layout.addWidget(self.config_api_btn)
        api_status_layout.addStretch()
        collection_layout.addLayout(api_status_layout)
        
        # Collection controls
        controls_layout = QHBoxLayout()
        
        self.collect_once_btn = QPushButton("📊 Collect Data Once")
        self.collect_once_btn.clicked.connect(self.collect_data_once)
        controls_layout.addWidget(self.collect_once_btn)
        
        self.start_continuous_btn = QPushButton("🔄 Start Continuous Collection")
        self.start_continuous_btn.clicked.connect(self.start_continuous_collection)
        controls_layout.addWidget(self.start_continuous_btn)
        
        self.stop_continuous_btn = QPushButton("⏹️ Stop Collection")
        self.stop_continuous_btn.setEnabled(False)
        self.stop_continuous_btn.clicked.connect(self.stop_continuous_collection)
        controls_layout.addWidget(self.stop_continuous_btn)
        
        controls_layout.addStretch()
        collection_layout.addLayout(controls_layout)
        
        # Collection progress
        self.collection_progress = QProgressBar()
        self.collection_status = QLabel("Ready")
        collection_layout.addWidget(self.collection_progress)
        collection_layout.addWidget(self.collection_status)
        
        layout.addWidget(collection_group)
        
        # Statistics section
        stats_group = QGroupBox("📊 System Statistics")
        stats_layout = QVBoxLayout(stats_group)
        
        self.stats_table = QTableWidget()
        self.stats_table.setColumnCount(2)
        self.stats_table.setHorizontalHeaderLabels(["Metric", "Value"])
        self.stats_table.horizontalHeader().setStretchLastSection(True)
        stats_layout.addWidget(self.stats_table)
        
        refresh_btn = QPushButton("🔄 Refresh Statistics")
        refresh_btn.clicked.connect(self.refresh_dashboard)
        stats_layout.addWidget(refresh_btn)
        
        layout.addWidget(stats_group)
        
        # Routes table
        routes_group = QGroupBox("🛣️ Monitored Routes")
        routes_layout = QVBoxLayout(routes_group)
        
        self.routes_table = QTableWidget()
        self.routes_table.setColumnCount(4)
        self.routes_table.setHorizontalHeaderLabels(["Route", "Samples", "Avg Speed", "Status"])
        self.routes_table.horizontalHeader().setStretchLastSection(True)
        routes_layout.addWidget(self.routes_table)
        
        layout.addWidget(routes_group)

        # Set the scroll content
        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll)

        return tab

    # ============== TAB 5: CALIBRATION CENTER ==============

    def create_calibration_tab(self):
        """Create dynamic calibration info tab"""
        from PyQt6.QtWidgets import QScrollArea

        tab = QWidget()
        main_layout = QVBoxLayout(tab)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Create scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Container widget for scrollable content
        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Header
        header_label = QLabel("🎯 Dynamic Calibration System")
        header_font = QFont()
        header_font.setPointSize(14)
        header_font.setBold(True)
        header_label.setFont(header_font)
        layout.addWidget(header_label)

        # Info
        info_label = QLabel(
            "Dynamic calibration automatically adjusts SUMO parameters IN REAL-TIME during simulation!\n\n"
            "Unlike traditional offline calibration that runs multiple simulations, dynamic calibration:\n"
            "• Learns while simulating (adaptive learning)\n"
            "• Adjusts parameters every 5 simulated minutes\n"
            "• Uses gradient descent to minimize error\n"
            "• Applies changes to vehicles on-the-fly\n\n"
            "This is ENABLED BY DEFAULT for all simulations."
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # Status
        status_group = QGroupBox("📊 Status")
        status_layout = QVBoxLayout(status_group)

        status_label = QLabel(
            "✅ Dynamic calibration is ACTIVE\n"
            "🔄 Automatically enabled for all simulations\n"
            "⚡ Real-time parameter optimization"
        )
        status_label.setWordWrap(True)
        status_layout.addWidget(status_label)

        layout.addWidget(status_group)

        # How it works
        how_it_works_group = QGroupBox("🔧 How It Works")
        how_it_works_layout = QVBoxLayout(how_it_works_group)

        how_it_works_text = QTextEdit()
        how_it_works_text.setReadOnly(True)
        how_it_works_text.setMaximumHeight(200)
        how_it_works_text.setPlainText(
            "1. SIMULATION STARTS\n"
            "   - Vehicles use default parameters\n"
            "   - System monitors speed and traffic flow\n\n"
            "2. ERROR CALCULATION (every 5 sim-minutes)\n"
            "   - Compare simulation speed vs real-world speed\n"
            "   - Calculate percentage error\n\n"
            "3. GRADIENT COMPUTATION\n"
            "   - Determine which direction to adjust each parameter\n"
            "   - Use heuristic rules based on traffic physics\n\n"
            "4. PARAMETER UPDATE\n"
            "   - Apply gradient descent: param = param - learning_rate * gradient\n"
            "   - Clip values to realistic bounds\n\n"
            "5. APPLY TO VEHICLES\n"
            "   - Update all active vehicles with new parameters\n"
            "   - Changes take effect immediately!\n\n"
            "6. REPEAT\n"
            "   - Continue adjusting until simulation ends\n"
            "   - Save final optimized parameters to database"
        )
        how_it_works_layout.addWidget(how_it_works_text)

        layout.addWidget(how_it_works_group)

        # Parameters being tuned
        params_group = QGroupBox("📋 Parameters Being Dynamically Tuned")
        params_layout = QVBoxLayout(params_group)

        params_table = QTableWidget()
        params_table.setColumnCount(3)
        params_table.setHorizontalHeaderLabels(["Parameter", "Description", "Effect on Traffic"])
        params_table.horizontalHeader().setStretchLastSection(True)

        params_data = [
            ("speedFactor", "Speed limit multiplier", "Higher = faster speeds"),
            ("tau", "Car-following headway", "Lower = closer following, faster flow"),
            ("accel", "Max acceleration", "Higher = faster acceleration"),
            ("decel", "Max deceleration", "Higher = harder braking"),
            ("sigma", "Driver imperfection", "Higher = more randomness, slower")
        ]

        params_table.setRowCount(len(params_data))
        for i, (param, desc, effect) in enumerate(params_data):
            params_table.setItem(i, 0, QTableWidgetItem(param))
            params_table.setItem(i, 1, QTableWidgetItem(desc))
            params_table.setItem(i, 2, QTableWidgetItem(effect))

        params_table.resizeColumnsToContents()
        params_layout.addWidget(params_table)

        layout.addWidget(params_group)

        # Configuration
        config_group = QGroupBox("⚙️ Configuration")
        config_layout = QVBoxLayout(config_group)

        config_label = QLabel(
            "Update Interval: Every 300 simulation steps (5 simulated minutes)\n"
            "Learning Rate: 0.1 (10% adjustment per update)\n"
            "History Window: Last 10 measurements\n\n"
            "To disable dynamic calibration, edit simulator.py:\n"
            "Set enable_dynamic_calibration=False in run_simulation()"
        )
        config_label.setWordWrap(True)
        config_layout.addWidget(config_label)

        layout.addWidget(config_group)

        # View results
        results_group = QGroupBox("📈 View Results")
        results_layout = QVBoxLayout(results_group)

        results_label = QLabel(
            "Dynamic calibration results are automatically saved to the database.\n"
            "View them in the 'Results & Analysis' tab after running a simulation.\n\n"
            "The system will show:\n"
            "• Initial vs final error\n"
            "• Parameter evolution over time\n"
            "• Improvement percentage"
        )
        results_label.setWordWrap(True)
        results_layout.addWidget(results_label)

        layout.addWidget(results_group)

        layout.addStretch()

        # Set the scroll content
        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll)

        return tab

    # ============== TAB 6: AI PREDICTION ==============

    def create_ai_tab(self):
        """Create AI prediction tab"""
        from PyQt6.QtWidgets import QScrollArea

        tab = QWidget()
        main_layout = QVBoxLayout(tab)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Create scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Container widget for scrollable content
        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Info
        info_label = QLabel(
            "AI Predictor uses machine learning to forecast traffic conditions\n"
            "based on historical patterns and current conditions."
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        # Training section
        training_group = QGroupBox("🎓 Model Training")
        training_layout = QVBoxLayout(training_group)
        
        self.ai_status_label = QLabel("Status: Not trained")
        training_layout.addWidget(self.ai_status_label)
        
        btn_layout = QHBoxLayout()
        
        self.train_ai_btn = QPushButton("🎓 Train Predictor")
        self.train_ai_btn.clicked.connect(self.train_ai_predictor)
        btn_layout.addWidget(self.train_ai_btn)
        
        self.validate_ai_btn = QPushButton("✓ Validate Accuracy")
        self.validate_ai_btn.clicked.connect(self.validate_ai_predictor)
        btn_layout.addWidget(self.validate_ai_btn)
        
        btn_layout.addStretch()
        training_layout.addLayout(btn_layout)
        
        self.ai_training_output = QTextEdit()
        self.ai_training_output.setReadOnly(True)
        self.ai_training_output.setMaximumHeight(150)
        training_layout.addWidget(self.ai_training_output)
        
        layout.addWidget(training_group)
        
        # Prediction section
        prediction_group = QGroupBox("🔮 Make Predictions")
        prediction_layout = QVBoxLayout(prediction_group)
        
        time_layout = QHBoxLayout()
        time_layout.addWidget(QLabel("Predict for time:"))
        self.pred_hour_spin = QSpinBox()
        self.pred_hour_spin.setRange(0, 23)
        self.pred_hour_spin.setValue(datetime.now().hour)
        time_layout.addWidget(self.pred_hour_spin)
        time_layout.addWidget(QLabel(":00"))
        time_layout.addStretch()
        
        self.predict_btn = QPushButton("🔮 Generate Predictions")
        self.predict_btn.clicked.connect(self.make_predictions)
        time_layout.addWidget(self.predict_btn)
        
        prediction_layout.addLayout(time_layout)
        
        # Predictions table
        self.predictions_table = QTableWidget()
        self.predictions_table.setColumnCount(5)
        self.predictions_table.setHorizontalHeaderLabels([
            "Route", "Predicted Time", "Confidence Lower", "Confidence Upper", "Samples"
        ])
        self.predictions_table.horizontalHeader().setStretchLastSection(True)
        prediction_layout.addWidget(self.predictions_table)
        
        layout.addWidget(prediction_group)

        # Set the scroll content
        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll)

        return tab

    # ============== TAB 7: RESULTS & ANALYSIS ==============

    def create_results_tab(self):
        """Create results and analysis tab"""
        from PyQt6.QtWidgets import QScrollArea

        tab = QWidget()
        main_layout = QVBoxLayout(tab)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Create scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        # Container widget for scrollable content
        scroll_content = QWidget()
        layout = QVBoxLayout(scroll_content)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # Scenarios section
        scenarios_group = QGroupBox("🔍 Simulation Scenarios")
        scenarios_layout = QVBoxLayout(scenarios_group)
        
        self.scenarios_table = QTableWidget()
        self.scenarios_table.setColumnCount(5)
        self.scenarios_table.setHorizontalHeaderLabels([
            "Scenario ID", "Date", "Error %", "Similarity %", "Status"
        ])
        self.scenarios_table.horizontalHeader().setStretchLastSection(True)
        scenarios_layout.addWidget(self.scenarios_table)
        
        btn_layout = QHBoxLayout()
        
        refresh_scenarios_btn = QPushButton("🔄 Refresh")
        refresh_scenarios_btn.clicked.connect(self.refresh_scenarios)
        btn_layout.addWidget(refresh_scenarios_btn)
        
        self.view_scenario_btn = QPushButton("👁️ View Details")
        self.view_scenario_btn.clicked.connect(self.view_scenario_details)
        btn_layout.addWidget(self.view_scenario_btn)

        self.visualize_btn = QPushButton("📊 Generate Visualization")
        self.visualize_btn.clicked.connect(self.generate_visualization_for_selected)
        btn_layout.addWidget(self.visualize_btn)

        self.export_results_btn = QPushButton("💾 Export Results")
        self.export_results_btn.clicked.connect(self.export_results)
        btn_layout.addWidget(self.export_results_btn)

        self.generate_report_btn = QPushButton("📝 Generate Summary Report")
        self.generate_report_btn.clicked.connect(self.generate_summary_report)
        btn_layout.addWidget(self.generate_report_btn)

        btn_layout.addStretch()
        scenarios_layout.addLayout(btn_layout)
        
        layout.addWidget(scenarios_group)
        
        # Comparison view
        comparison_group = QGroupBox("📊 Latest Comparison")
        comparison_layout = QVBoxLayout(comparison_group)

        self.comparison_text = QTextEdit()
        self.comparison_text.setReadOnly(True)
        comparison_layout.addWidget(self.comparison_text)

        layout.addWidget(comparison_group)

        # Route Estimation section - NEW!
        route_est_group = QGroupBox("🗺️ Route Time Estimation (Based on Simulation)")
        route_est_layout = QVBoxLayout(route_est_group)

        # Instructions
        inst_label = QLabel(
            "Click on the map below to select your route:\n"
            "1️⃣ First click = Origin (starting point) - shown in GREEN\n"
            "2️⃣ Second click = Destination (end point) - shown in RED\n"
            "Then click 'Estimate Travel Time' to get results based on simulation data."
        )
        inst_label.setWordWrap(True)
        inst_label.setStyleSheet("background-color: #E3F2FD; padding: 10px; border-radius: 5px; font-size: 11pt;")
        route_est_layout.addWidget(inst_label)

        # Map for point selection
        self.route_map_view = QWebEngineView()
        self.route_map_view.setMinimumHeight(400)

        # Enable web features for loading external resources (Leaflet CDN)
        from PyQt6.QtWebEngineCore import QWebEngineSettings
        settings = self.route_map_view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)

        route_est_layout.addWidget(self.route_map_view)

        # Selected points display
        self.route_selection_label = QLabel("❓ No points selected yet. Click on the map to select origin and destination.")
        self.route_selection_label.setWordWrap(True)
        self.route_selection_label.setStyleSheet("padding: 10px; background: #FFF3E0; border-radius: 5px; font-size: 10pt;")
        route_est_layout.addWidget(self.route_selection_label)

        # Clear selection button
        route_action_layout = QHBoxLayout()

        clear_route_btn = QPushButton("🔄 Clear Selection & Start Over")
        clear_route_btn.clicked.connect(self.clear_route_selection)
        clear_route_btn.setStyleSheet("padding: 8px;")
        route_action_layout.addWidget(clear_route_btn)

        refresh_map_btn = QPushButton("🗺️ Refresh Map (Center on Simulated Area)")
        refresh_map_btn.clicked.connect(lambda: self.init_route_map())
        refresh_map_btn.setStyleSheet("padding: 8px;")
        route_action_layout.addWidget(refresh_map_btn)

        route_action_layout.addStretch()
        route_est_layout.addLayout(route_action_layout)

        # Store selected points
        self.route_origin = None
        self.route_destination = None

        # Data source and timing options
        options_group = QGroupBox("Simulation & Validation Options")
        options_layout = QVBoxLayout()

        # Historical data checkbox
        self.use_historical_data_check = QCheckBox("Use stored historical data (skip real-time API call)")
        self.use_historical_data_check.setToolTip(
            "When checked, uses previously collected data from database instead of fetching fresh data from Google Maps API.\n"
            "Useful when you have already collected typical traffic patterns."
        )
        self.use_historical_data_check.setChecked(False)
        options_layout.addWidget(self.use_historical_data_check)

        # Validation time selection
        time_select_layout = QHBoxLayout()
        time_select_layout.addWidget(QLabel("Validation Time:"))

        self.validation_time_combo = QComboBox()
        self.validation_time_combo.addItems([
            "Current time (real-time traffic)",
            "Monday 8:00 AM (typical)",
            "Monday 12:00 PM (typical)",
            "Monday 5:00 PM (typical)",
            "Monday 8:00 PM (typical)",
            "Tuesday 8:00 AM (typical)",
            "Tuesday 5:00 PM (typical)",
            "Wednesday 8:00 AM (typical)",
            "Wednesday 5:00 PM (typical)",
            "Thursday 8:00 AM (typical)",
            "Thursday 5:00 PM (typical)",
            "Friday 8:00 AM (typical)",
            "Friday 5:00 PM (typical)",
            "Saturday 8:00 AM (typical)",
            "Saturday 5:00 PM (typical)",
            "Sunday 8:00 AM (typical)",
            "Sunday 5:00 PM (typical)"
        ])
        self.validation_time_combo.setToolTip(
            "Select when to validate:\n"
            "- Current time: Fetches real-time traffic from Google Maps now\n"
            "- Typical times: Uses typical traffic patterns for that day/time (if using historical data)"
        )
        time_select_layout.addWidget(self.validation_time_combo)
        time_select_layout.addStretch()
        options_layout.addLayout(time_select_layout)

        options_group.setLayout(options_layout)
        route_est_layout.addWidget(options_group)

        # Buttons
        route_btn_layout = QHBoxLayout()

        self.targeted_sim_btn = QPushButton("🎯 Run Targeted Simulation")
        self.targeted_sim_btn.setStyleSheet("background-color: #FF9800; padding: 10px; font-weight: bold;")
        self.targeted_sim_btn.setToolTip("Generate traffic on your selected route to collect data before estimation")
        self.targeted_sim_btn.clicked.connect(self.run_targeted_simulation)
        route_btn_layout.addWidget(self.targeted_sim_btn)

        self.estimate_route_btn = QPushButton("📍 Estimate Travel Time")
        self.estimate_route_btn.setStyleSheet("background-color: #2196F3; padding: 10px; font-weight: bold;")
        self.estimate_route_btn.clicked.connect(self.estimate_route_time)
        route_btn_layout.addWidget(self.estimate_route_btn)

        self.compare_google_btn = QPushButton("🌐 Compare with Google Maps")
        self.compare_google_btn.setStyleSheet("background-color: #4CAF50; padding: 10px; font-weight: bold;")
        self.compare_google_btn.clicked.connect(self.compare_route_with_google)
        route_btn_layout.addWidget(self.compare_google_btn)

        route_btn_layout.addStretch()
        route_est_layout.addLayout(route_btn_layout)

        # Results display
        self.route_estimate_text = QTextEdit()
        self.route_estimate_text.setReadOnly(True)
        self.route_estimate_text.setMaximumHeight(250)
        route_est_layout.addWidget(self.route_estimate_text)

        layout.addWidget(route_est_group)

        # Set the scroll content
        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll)

        return tab

    # ============== ORIGINAL MAP FUNCTIONS (UNTOUCHED) ==============

    def handle_js_console_message(self, level, message, lineNumber, sourceID):
        """Handle JavaScript console messages"""
        print(f"[JS Console] {message} (line {lineNumber})")

    def log(self, text, level="INFO"):
        """Log messages with color coding"""
        color_map = {
            "INFO": "#2196F3",
            "SUCCESS": "#4CAF50",
            "WARNING": "#FF9800",
            "ERROR": "#F44336"
        }
        color = color_map.get(level, "#333")
        self.console.append(f'<span style="color: {color}; font-weight: bold;">[{level}]</span> {text}')
        QApplication.processEvents()

    def init_map(self, center, zoom):
        """Initialize the map with drawing tools"""
        m = folium.Map(
            location=center,
            zoom_start=zoom,
            tiles='OpenStreetMap',
            control_scale=True
        )

        # Add draw control with rectangle only for area selection
        draw = plugins.Draw(
            export=True,
            position='topleft',
            draw_options={
                'polyline': False,
                'polygon': False,
                'circle': False,
                'marker': False,
                'circlemarker': False,
                'rectangle': {
                    'shapeOptions': {
                        'color': '#2196F3',
                        'weight': 3,
                        'fillOpacity': 0.2
                    }
                }
            }
        )
        draw.add_to(m)

        # Add JavaScript to capture drawn rectangle using QWebChannel
        js_code = """
        <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
        <script>
        (function() {
            console.log('[INIT] Starting initialization...');
            var bridgeObj = null;

            // Initialize QWebChannel immediately
            function initBridge() {
                if (typeof qt === 'undefined' || !qt.webChannelTransport) {
                    console.error('[ERROR] Qt WebChannel not available!');
                    return false;
                }

                console.log('[INIT] Creating QWebChannel...');
                new QWebChannel(qt.webChannelTransport, function(channel) {
                    bridgeObj = channel.objects.bridge;
                    console.log('[SUCCESS] Bridge connected!', bridgeObj);

                    if (bridgeObj && typeof bridgeObj.receiveRegion === 'function') {
                        console.log('[SUCCESS] bridge.receiveRegion is available');
                    } else {
                        console.error('[ERROR] bridge.receiveRegion not found!');
                    }

                    attachMapListener();
                });
                return true;
            }

            function attachMapListener() {
                console.log('[INIT] Waiting for map object...');

                var attempts = 0;
                var maxAttempts = 100;

                var checkMap = setInterval(function() {
                    attempts++;

                    if (typeof map !== 'undefined' && map) {
                        clearInterval(checkMap);
                        console.log('[SUCCESS] Map object found!');

                        map.on('draw:created', function(e) {
                            console.log('[EVENT] Rectangle drawn!');

                            try {
                                var layer = e.layer;
                                var bounds = layer.getBounds();

                                var data = {
                                    north: bounds.getNorth(),
                                    south: bounds.getSouth(),
                                    east: bounds.getEast(),
                                    west: bounds.getWest()
                                };

                                console.log('[DATA] Bounds:', JSON.stringify(data, null, 2));

                                if (bridgeObj && typeof bridgeObj.receiveRegion === 'function') {
                                    console.log('[SEND] Calling bridge.receiveRegion...');
                                    bridgeObj.receiveRegion(JSON.stringify(data));
                                    console.log('[SEND] Data sent successfully!');
                                } else {
                                    console.error('[ERROR] Bridge not ready or method missing!');
                                    alert('Connection error! Please restart the application.');
                                }
                            } catch (error) {
                                console.error('[ERROR] Exception:', error);
                                alert('Error processing selection: ' + error.message);
                            }
                        });

                        console.log('[SUCCESS] Draw listener attached!');

                    } else if (attempts >= maxAttempts) {
                        clearInterval(checkMap);
                        console.error('[ERROR] Map object not found after ' + maxAttempts + ' attempts');
                    }
                }, 50);
            }

            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', function() {
                    console.log('[INIT] DOM ready');
                    initBridge();
                });
            } else {
                console.log('[INIT] DOM already ready');
                initBridge();
            }
        })();
        </script>
        """

        m.get_root().html.add_child(folium.Element(js_code))

        folium.LayerControl().add_to(m)

        map_path = os.path.abspath(self.map_file)
        m.save(map_path)

        print(f"[DEBUG] Map saved to: {map_path}")
        print(f"[DEBUG] File exists: {os.path.exists(map_path)}")

        file_url = QUrl.fromLocalFile(map_path)
        print(f"[DEBUG] Loading URL: {file_url.toString()}")

        self.view.setUrl(file_url)

    def on_map_loaded(self, ok):
        """Called when map finishes loading"""
        if ok:
            self.log("Map loaded successfully", "SUCCESS")
            print("[DEBUG] Map loaded, injecting listener code...")

            inject_code = """
            (function() {
                console.log('[INJECT] Running injected code...');

                function findMapVariable() {
                    for (var key in window) {
                        if (key.startsWith('map_') && window[key] && typeof window[key].on === 'function') {
                            return window[key];
                        }
                    }
                    return null;
                }

                var attempts = 0;
                var checkReady = setInterval(function() {
                    attempts++;
                    var mapObj = findMapVariable();

                    if (mapObj && typeof QWebChannel !== 'undefined' && typeof qt !== 'undefined') {
                        clearInterval(checkReady);
                        console.log('[INJECT] Map and QWebChannel ready! Attempts:', attempts);

                        new QWebChannel(qt.webChannelTransport, function(channel) {
                            var bridge = channel.objects.bridge;
                            console.log('[INJECT] Bridge obtained:', bridge);

                            mapObj.on('draw:created', function(e) {
                                console.log('[INJECT] Draw event fired!');
                                var bounds = e.layer.getBounds();
                                var data = JSON.stringify({
                                    north: bounds.getNorth(),
                                    south: bounds.getSouth(),
                                    east: bounds.getEast(),
                                    west: bounds.getWest()
                                });
                                console.log('[INJECT] Data:', data);
                                console.log('[INJECT] Calling bridge.receiveRegion...');
                                bridge.receiveRegion(data);
                                console.log('[INJECT] Done!');
                            });

                            console.log('[INJECT] Setup complete! Listener attached to map.');
                        });
                    } else if (attempts > 100) {
                        clearInterval(checkReady);
                        console.error('[INJECT] Failed to initialize after 100 attempts');
                        console.error('[INJECT] mapObj:', mapObj, 'QWebChannel:', typeof QWebChannel, 'qt:', typeof qt);
                    }
                }, 100);
            })();
            """

            self.view.page().runJavaScript(inject_code)
            print("[DEBUG] JavaScript injected")
        else:
            self.log("Map failed to load", "ERROR")

    def on_search(self):
        """Handle location search"""
        loc = self.location_input.text().strip()
        if not loc:
            self.log("Please enter a location first.", "ERROR")
            return

        self.log(f"Searching for: {loc}", "INFO")

        try:
            geolocator = Nominatim(user_agent="digital_twin_traffic_simulator")
            geo = geolocator.geocode(loc)

            if not geo:
                self.log(f"Location '{loc}' not found. Please try a different search term.", "ERROR")
                return

            self.current_location = loc
            self.log(f"Found: {geo.address}", "SUCCESS")
            self.log(f"Coordinates: {geo.latitude:.4f}, {geo.longitude:.4f}", "INFO")
            self.init_map([geo.latitude, geo.longitude], 13)

        except Exception as e:
            self.log(f"Search error: {str(e)}", "ERROR")

    def on_region_selected(self, data):
        """Handle region selection from map - WITH AUTO ROUTE GENERATION"""
        print(f"[DEBUG] on_region_selected called with data: {data}")
        try:
            coords = json.loads(data)
            self.selected_bbox = coords
            self.selected_network_file = None  # Clear cached network when drawing new area
            print(f"[DEBUG] Parsed coordinates: {coords}")

            # Calculate approximate area
            lat_diff = abs(coords['north'] - coords['south'])
            lon_diff = abs(coords['east'] - coords['west'])
            area_km2 = lat_diff * lon_diff * 111 * 111

            self.selection_label.setText(
                f"✅ Area selected: {area_km2:.2f} km² | "
                f"Bounds: ({coords['south']:.4f}, {coords['west']:.4f}) to "
                f"({coords['north']:.4f}, {coords['east']:.4f})"
            )
            self.selection_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            self.clear_btn.setEnabled(True)

            self.log(f"Region selected: {area_km2:.2f} km²", "SUCCESS")
            self.log(f"Bounds: N={coords['north']:.4f}, S={coords['south']:.4f}, "
                    f"E={coords['east']:.4f}, W={coords['west']:.4f}", "INFO")
            self.log("", "INFO")
            self.log("✅ Area ready for simulation!", "SUCCESS")
            self.log("   Routes will be generated automatically from network topology", "INFO")
            self.log("", "INFO")

            print(f"[DEBUG] self.selected_bbox is now: {self.selected_bbox}")

        except Exception as e:
            self.log(f"Error processing region: {str(e)}", "ERROR")
            print(f"[DEBUG] Exception in on_region_selected: {e}")
            import traceback
            traceback.print_exc()

    def on_clear_selection(self):
        """Clear the current selection"""
        self.selected_bbox = None
        self.selected_network_file = None  # Clear selected cached network
        self.selection_label.setText("📌 No area selected")
        self.selection_label.setStyleSheet("")
        self.clear_btn.setEnabled(False)
        self.log("Selection cleared", "INFO")

        if self.current_location:
            geolocator = Nominatim(user_agent="digital_twin_traffic_simulator")
            geo = geolocator.geocode(self.current_location)
            if geo:
                self.init_map([geo.latitude, geo.longitude], 13)
        else:
            self.init_map([30.0444, 31.2357], 12)

    # ============== AREA TRAINING MAP FUNCTIONS ==============

    def init_area_map(self, center, zoom):
        """Initialize the area training map with drawing tools - EXACT COPY FROM TAB 1"""
        m = folium.Map(
            location=center,
            zoom_start=zoom,
            tiles='OpenStreetMap',
            control_scale=True
        )

        # Add draw control with rectangle only for area selection
        draw = plugins.Draw(
            export=True,
            position='topleft',
            draw_options={
                'polyline': False,
                'polygon': False,
                'circle': False,
                'marker': False,
                'circlemarker': False,
                'rectangle': {
                    'shapeOptions': {
                        'color': '#4CAF50',
                        'weight': 3,
                        'fillOpacity': 0.2
                    }
                }
            }
        )
        draw.add_to(m)

        # Add JavaScript to capture drawn rectangle using QWebChannel - EXACT COPY FROM TAB 1
        js_code = """
        <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
        <script>
        (function() {
            console.log('[INIT] Starting initialization...');
            var bridgeObj = null;

            // Initialize QWebChannel immediately
            function initBridge() {
                if (typeof qt === 'undefined' || !qt.webChannelTransport) {
                    console.error('[ERROR] Qt WebChannel not available!');
                    return false;
                }

                console.log('[INIT] Creating QWebChannel...');
                new QWebChannel(qt.webChannelTransport, function(channel) {
                    bridgeObj = channel.objects.bridge;
                    console.log('[SUCCESS] Bridge connected!', bridgeObj);

                    if (bridgeObj && typeof bridgeObj.receiveRegion === 'function') {
                        console.log('[SUCCESS] bridge.receiveRegion is available');
                    } else {
                        console.error('[ERROR] bridge.receiveRegion not found!');
                    }

                    attachMapListener();
                });
                return true;
            }

            function attachMapListener() {
                console.log('[INIT] Waiting for map object...');

                var attempts = 0;
                var maxAttempts = 100;

                var checkMap = setInterval(function() {
                    attempts++;

                    if (typeof map !== 'undefined' && map) {
                        clearInterval(checkMap);
                        console.log('[SUCCESS] Map object found!');

                        map.on('draw:created', function(e) {
                            console.log('[EVENT] Rectangle drawn!');

                            try {
                                var layer = e.layer;
                                var bounds = layer.getBounds();

                                var data = {
                                    north: bounds.getNorth(),
                                    south: bounds.getSouth(),
                                    east: bounds.getEast(),
                                    west: bounds.getWest()
                                };

                                console.log('[DATA] Bounds:', JSON.stringify(data, null, 2));

                                if (bridgeObj && typeof bridgeObj.receiveRegion === 'function') {
                                    console.log('[SEND] Calling bridge.receiveRegion...');
                                    bridgeObj.receiveRegion(JSON.stringify(data));
                                    console.log('[SEND] Data sent successfully!');
                                } else {
                                    console.error('[ERROR] Bridge not ready or method missing!');
                                    alert('Connection error! Please restart the application.');
                                }
                            } catch (error) {
                                console.error('[ERROR] Exception:', error);
                                alert('Error processing selection: ' + error.message);
                            }
                        });

                        console.log('[SUCCESS] Draw listener attached!');

                    } else if (attempts >= maxAttempts) {
                        clearInterval(checkMap);
                        console.error('[ERROR] Map object not found after ' + maxAttempts + ' attempts');
                    }
                }, 50);
            }

            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', function() {
                    console.log('[INIT] DOM ready');
                    initBridge();
                });
            } else {
                console.log('[INIT] DOM already ready');
                initBridge();
            }
        })();
        </script>
        """

        m.get_root().html.add_child(folium.Element(js_code))

        folium.LayerControl().add_to(m)

        map_path = os.path.abspath(self.area_map_file)
        m.save(map_path)

        print(f"[DEBUG] Area map saved to: {map_path}")
        print(f"[DEBUG] File exists: {os.path.exists(map_path)}")

        file_url = QUrl.fromLocalFile(map_path)
        print(f"[DEBUG] Loading URL: {file_url.toString()}")

        self.area_map_view.setUrl(file_url)

    def on_area_map_loaded(self, ok):
        """Called when area training map finishes loading - EXACT COPY FROM TAB 1"""
        if ok:
            print("[DEBUG] Area map loaded successfully")
            print("[DEBUG] Injecting listener code...")

            inject_code = """
            (function() {
                console.log('[INJECT] Running injected code...');

                function findMapVariable() {
                    for (var key in window) {
                        if (key.startsWith('map_') && window[key] && typeof window[key].on === 'function') {
                            return window[key];
                        }
                    }
                    return null;
                }

                var attempts = 0;
                var checkReady = setInterval(function() {
                    attempts++;
                    var mapObj = findMapVariable();

                    if (mapObj && typeof QWebChannel !== 'undefined' && typeof qt !== 'undefined') {
                        clearInterval(checkReady);
                        console.log('[INJECT] Map and QWebChannel ready! Attempts:', attempts);

                        new QWebChannel(qt.webChannelTransport, function(channel) {
                            var bridge = channel.objects.bridge;
                            console.log('[INJECT] Bridge obtained:', bridge);

                            mapObj.on('draw:created', function(e) {
                                console.log('[INJECT] Draw event fired!');
                                var bounds = e.layer.getBounds();
                                var data = JSON.stringify({
                                    north: bounds.getNorth(),
                                    south: bounds.getSouth(),
                                    east: bounds.getEast(),
                                    west: bounds.getWest()
                                });
                                console.log('[INJECT] Data:', data);
                                console.log('[INJECT] Calling bridge.receiveRegion...');
                                bridge.receiveRegion(data);
                                console.log('[INJECT] Done!');
                            });

                            console.log('[INJECT] Setup complete! Listener attached to map.');
                        });
                    } else if (attempts > 100) {
                        clearInterval(checkReady);
                        console.error('[INJECT] Failed to initialize after 100 attempts');
                        console.error('[INJECT] mapObj:', mapObj, 'QWebChannel:', typeof QWebChannel, 'qt:', typeof qt);
                    }
                }, 100);
            })();
            """

            self.area_map_view.page().runJavaScript(inject_code)
            print("[DEBUG] JavaScript injected")
        else:
            print("[DEBUG] Area map failed to load")

    def on_area_region_selected(self, data):
        """Handle region selection from area training map"""
        print(f"[DEBUG] on_area_region_selected called with data: {data}")
        try:
            coords = json.loads(data)
            self.area_selected_bbox = coords
            print(f"[DEBUG] Parsed area coordinates: {coords}")

            # Calculate approximate area
            lat_diff = abs(coords['north'] - coords['south'])
            lon_diff = abs(coords['east'] - coords['west'])
            area_km2 = lat_diff * lon_diff * 111 * 111

            self.area_bbox_label.setText(
                f"Area selected: {area_km2:.2f} km²\n"
                f"Bounds: ({coords['south']:.4f}, {coords['west']:.4f}) to "
                f"({coords['north']:.4f}, {coords['east']:.4f})"
            )
            self.area_bbox_label.setStyleSheet("color: #4CAF50; font-weight: bold;")

            print(f"[DEBUG] Area map selection complete")

        except Exception as e:
            print(f"[DEBUG] Exception in on_area_region_selected: {e}")
            import traceback
            traceback.print_exc()

    def view_cached_networks(self):
        """Show dialog with list of cached networks"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QListWidget, QLabel, QPushButton, QHBoxLayout, QMessageBox
        from modules.network_builder import get_cached_networks, clear_all_cache

        dialog = QDialog(self)
        dialog.setWindowTitle("💾 Cached Networks")
        dialog.setMinimumWidth(700)
        dialog.setMinimumHeight(450)

        layout = QVBoxLayout(dialog)

        # Info label
        info_label = QLabel("Select a cached network to load it directly (no need to select area on map):")
        info_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        layout.addWidget(info_label)

        # Get cached networks
        cache_dir = os.path.join("data", "networks")
        os.makedirs(cache_dir, exist_ok=True)
        cached_networks = get_cached_networks(cache_dir)

        list_widget = None

        if not cached_networks:
            no_cache_label = QLabel("❌ No cached networks found.\n\nCached networks will appear here after you run your first simulation.")
            no_cache_label.setFont(QFont("Segoe UI", 11))
            no_cache_label.setStyleSheet("color: #666; padding: 20px;")
            layout.addWidget(no_cache_label)
        else:
            # List widget
            list_widget = QListWidget()
            list_widget.setFont(QFont("Segoe UI", 10))
            list_widget.setSelectionMode(QListWidget.SelectionMode.SingleSelection)

            for i, cache in enumerate(cached_networks):
                bbox = cache['bbox']
                item_text = (
                    f"📍 {cache['location']} | "
                    f"Nodes: {cache['nodes']:,} | Edges: {cache['edges']:,} | "
                    f"Size: {cache['size_mb']:.1f} MB\n"
                    f"   Area: ({bbox['south']:.4f}, {bbox['west']:.4f}) to ({bbox['north']:.4f}, {bbox['east']:.4f})"
                )
                list_widget.addItem(item_text)

            # Store cached_networks in list widget for later access
            list_widget.setProperty("cached_networks", cached_networks)

            layout.addWidget(list_widget)

            # Info text
            info_text = QLabel(
                f"✅ Found {len(cached_networks)} cached network(s)\n\n"
                "💡 Click 'Load Selected' to use the network without selecting area on map."
            )
            info_text.setFont(QFont("Segoe UI", 9))
            info_text.setStyleSheet("color: #4CAF50; padding: 10px; background: #E8F5E9; border-radius: 5px;")
            layout.addWidget(info_text)

        # Buttons
        button_layout = QHBoxLayout()

        if cached_networks and list_widget:
            # Load selected button
            load_btn = QPushButton("✅ Load Selected Network")
            load_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            load_btn.setStyleSheet("background-color: #4CAF50; color: white; padding: 8px;")
            load_btn.clicked.connect(lambda: self.load_cached_network(dialog, list_widget))
            button_layout.addWidget(load_btn)

        button_layout.addStretch()

        if cached_networks:
            clear_btn = QPushButton("🗑️ Clear All Cache")
            clear_btn.clicked.connect(lambda: self.clear_cache_confirm(dialog, cache_dir))
            button_layout.addWidget(clear_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)

        dialog.exec()

    def load_cached_network(self, dialog, list_widget):
        """Load the selected cached network"""
        from PyQt6.QtWidgets import QMessageBox

        selected_items = list_widget.selectedItems()
        if not selected_items:
            QMessageBox.warning(
                self,
                "No Selection",
                "Please select a cached network from the list."
            )
            return

        # Get selected index
        selected_index = list_widget.row(selected_items[0])
        cached_networks = list_widget.property("cached_networks")
        selected_cache = cached_networks[selected_index]

        # Set the bbox and network file
        self.selected_bbox = selected_cache['bbox']
        self.selected_network_file = selected_cache.get('net_file')  # Store the selected network file

        # Update UI to show loaded network
        bbox = selected_cache['bbox']
        lat_diff = abs(bbox['north'] - bbox['south'])
        lon_diff = abs(bbox['east'] - bbox['west'])
        area_km2 = lat_diff * lon_diff * 111 * 111

        self.selection_label.setText(
            f"✅ Loaded from cache: {selected_cache['location']}\n"
            f"Area: {area_km2:.2f} km² | "
            f"Nodes: {selected_cache['nodes']:,} | Edges: {selected_cache['edges']:,}\n"
            f"Bounds: ({bbox['south']:.4f}, {bbox['west']:.4f}) to "
            f"({bbox['north']:.4f}, {bbox['east']:.4f})"
        )
        self.selection_label.setStyleSheet("color: #2196F3; font-weight: bold; background: #E3F2FD; padding: 10px; border-radius: 5px;")

        # Log it
        self.log(f"📂 Loaded cached network: {selected_cache['location']}", "SUCCESS")
        self.log(f"   Network has {selected_cache['nodes']:,} nodes and {selected_cache['edges']:,} edges", "INFO")
        self.log("   Ready to run simulation!", "INFO")

        # Close dialog
        dialog.accept()

        QMessageBox.information(
            self,
            "Network Loaded",
            f"✅ Loaded cached network: {selected_cache['location']}\n\n"
            f"You can now click 'Run Simulation' to start immediately!"
        )

    def clear_cache_confirm(self, parent_dialog, cache_dir):
        """Confirm and clear all cached networks"""
        from PyQt6.QtWidgets import QMessageBox
        from modules.network_builder import clear_all_cache

        reply = QMessageBox.question(
            self,
            "Clear Cache",
            "Are you sure you want to delete all cached networks?\n\n"
            "You will need to re-download them next time.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            count = clear_all_cache(cache_dir)
            QMessageBox.information(
                self,
                "Cache Cleared",
                f"Deleted {count} cached file(s)."
            )
            parent_dialog.accept()  # Close the dialog
            self.log(f"Cleared {count} cached network file(s)", "INFO")

    def on_run(self):
        """Run the simulation with Digital Twin integration"""
        print(f"[DEBUG] on_run called. self.selected_bbox = {self.selected_bbox}")

        if not self.selected_bbox:
            self.log("Please select an area on the map first by drawing a rectangle!", "WARNING")
            print("[DEBUG] No bbox selected, aborting simulation")
            return

        location = self.location_input.text() or "custom_area"
        duration = self.duration.value()
        intensity = self.intensity.currentText()

        self.log("=" * 60, "INFO")
        self.log(f"Starting DIGITAL TWIN simulation for: {location}", "INFO")
        self.log(f"Duration: {duration}s | Traffic: {intensity}", "INFO")
        self.log("=" * 60, "INFO")

        try:
            self.run_btn.setEnabled(False)
            self.run_btn.setText("⏳ Running...")

            out_dir = os.path.join("data", "networks")
            os.makedirs(out_dir, exist_ok=True)

            # Calculate area size and warn if too large
            lat_range = self.selected_bbox['north'] - self.selected_bbox['south']
            lon_range = self.selected_bbox['east'] - self.selected_bbox['west']
            area_km2 = lat_range * 111 * lon_range * 111  # Approximate area

            if area_km2 > 100:
                self.log(f"⚠️ Selected area is LARGE ({area_km2:.0f} km²)", "WARNING")
                self.log("   This may take several minutes. Consider selecting a smaller area.", "WARNING")
            elif area_km2 > 50:
                self.log(f"Selected area: {area_km2:.0f} km² (medium size)", "INFO")
            else:
                self.log(f"Selected area: {area_km2:.0f} km² (good size for quick simulation)", "INFO")

            self.log("Loading or downloading network for selected area...", "INFO")
            net_path = generate_network_from_bbox(
                self.selected_bbox,
                location,
                out_dir
            )
            self.log(f"Network ready: {os.path.basename(net_path)}", "SUCCESS")

            self.log("Generating traffic demand...", "INFO")
            route_path = generate_routes(
                net_path,
                os.path.join("data", "routes"),
                sim_time=duration
            )
            self.log(f"Routes generated: {os.path.basename(route_path)}", "SUCCESS")

            self.log("Creating simulation configuration...", "INFO")
            cfg_path = create_config(
                net_path,
                route_path,
                os.path.join("data", "configs", "simulation.sumocfg"),
                sim_time=duration
            )
            self.log(f"Config created: {os.path.basename(cfg_path)}", "SUCCESS")

            scenario_id = f"{location.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

            # ============ COLLECT REAL-WORLD DATA FOR CALIBRATION ============
            if self.api_key:
                self.log("=" * 60, "INFO")
                self.log("📡 Collecting real-world traffic data for selected area...", "INFO")
                self.log("=" * 60, "INFO")

                try:
                    # Generate sample routes within the selected bbox
                    route_gen = SimpleRouteGenerator()
                    sample_routes = route_gen.generate_routes_for_bbox(self.selected_bbox, num_routes=5)

                    self.log(f"Generated {len(sample_routes)} sample routes in selected area", "INFO")

                    # Collect Google Maps data for each route
                    collector = TrafficDataCollector(self.api_key)
                    collected_count = 0

                    for route in sample_routes:
                        self.log(f"  Fetching: {route['name']}...", "INFO")

                        data = collector.fetch_route_traffic(
                            origin_lat=route['origin_lat'],
                            origin_lon=route['origin_lon'],
                            dest_lat=route['dest_lat'],
                            dest_lon=route['dest_lon'],
                            route_id=None  # Don't store in probe_routes
                        )

                        if data:
                            # Store as area-based data for calibration
                            self.db.conn.execute("""
                                INSERT INTO real_traffic_data
                                (area_id, timestamp, travel_time_seconds, distance_meters,
                                 traffic_delay_seconds, speed_kmh, data_source,
                                 origin_lat, origin_lon, dest_lat, dest_lon)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                scenario_id,
                                data['timestamp'],
                                data['travel_time_seconds'],
                                data['distance_meters'],
                                data['traffic_delay_seconds'],
                                data['speed_kmh'],
                                'google_maps',
                                route['origin_lat'],
                                route['origin_lon'],
                                route['dest_lat'],
                                route['dest_lon']
                            ))
                            self.db.conn.commit()

                            collected_count += 1
                            self.log(f"    ✓ Speed: {data['speed_kmh']:.1f} km/h, "
                                   f"Time: {data['travel_time_seconds']}s", "SUCCESS")

                    self.log("", "INFO")
                    self.log(f"✅ Collected real-world data: {collected_count}/{len(sample_routes)} routes", "SUCCESS")
                    self.log("   This data will be used for dynamic calibration!", "INFO")
                    self.log("=" * 60, "INFO")

                except Exception as e:
                    self.log(f"⚠️ Could not collect real-world data: {str(e)}", "WARNING")
                    self.log("   Calibration will use default urban speed (36.9 km/h)", "INFO")
                    import traceback
                    traceback.print_exc()
            else:
                self.log("⚠️ No API key configured - calibration will use default speed", "WARNING")
                self.log("   Configure API key in 'Data Collection' tab for real-world data", "INFO")
            # ================================================================

            # ============ CONFIGURE SIMULATION TO MATCH REAL CAIRO TRAFFIC ============
            self.log("", "INFO")
            self.log("Configuring simulation to match real Cairo traffic conditions...", "INFO")
            cairo_params = None  # Will hold Cairo parameters for dynamic calibrator
            try:
                from modules.traffic_configurator import TrafficConfigurator
                configurator = TrafficConfigurator()
                config_result = configurator.configure_simulation(scenario_id, route_path)

                if config_result.get('success'):
                    cairo_params = config_result.get('params')  # Get Cairo parameters
                    self.log("✅ Simulation configured for Cairo-style traffic", "SUCCESS")
                    self.log("   Vehicle parameters and density adjusted to match real data", "INFO")
                else:
                    self.log("⚠️ Could not configure traffic - using default parameters", "WARNING")

            except Exception as e:
                self.log(f"⚠️ Traffic configuration failed: {str(e)}", "WARNING")
                self.log("   Simulation will use default parameters", "INFO")
                import traceback
                traceback.print_exc()
            # ==========================================================================

            self.log("", "INFO")
            self.log("=" * 60, "INFO")
            self.log("🔬 DIGITAL TWIN MODE ENABLED", "INFO")
            self.log("🎯 DYNAMIC CALIBRATION ENABLED", "INFO")
            self.log(f"Scenario ID: {scenario_id}", "INFO")
            self.log("Parameters will adapt in real-time to match real traffic", "INFO")
            self.log("=" * 60, "INFO")

            self.log("Launching SUMO simulation...", "INFO")
            run_simulation(
                cfg_path,
                gui=True,
                scenario_id=scenario_id,
                enable_digital_twin=True,
                enable_dynamic_calibration=True,  # ENABLED: Real-time parameter adaptation
                initial_params=cairo_params  # Pass Cairo parameters to calibrator!
            )

            self.log("=" * 60, "SUCCESS")
            self.log("✅ Simulation completed successfully!", "SUCCESS")
            self.log("=" * 60, "SUCCESS")

            self.log("", "INFO")
            self.log("📊 DIGITAL TWIN RESULTS:", "INFO")
            self.log(f"View detailed comparison using:", "INFO")
            self.log(f"  python test_digital_twin_comparison.py", "INFO")
            self.log(f"Or check the database for scenario: {scenario_id}", "INFO")

        except Exception as e:
            self.log("=" * 60, "ERROR")
            self.log(f"❌ Simulation failed: {str(e)}", "ERROR")
            self.log("=" * 60, "ERROR")
            import traceback
            traceback.print_exc()

        finally:
            self.run_btn.setEnabled(True)
            self.run_btn.setText("▶️ Run Simulation")

    # ============== NEW TAB HELPER METHODS ==============

    def refresh_dashboard(self):
        """Refresh dashboard statistics"""
        try:
            stats = self.db.get_summary_stats()
            
            stats_data = [
                ("Active Probe Routes", str(stats['active_routes'])),
                ("Real Data Points", str(stats['real_data_points'])),
                ("Simulation Results", str(stats['simulation_results'])),
                ("Scenarios", str(stats['scenarios']))
            ]
            
            self.stats_table.setRowCount(len(stats_data))
            for i, (metric, value) in enumerate(stats_data):
                self.stats_table.setItem(i, 0, QTableWidgetItem(metric))
                self.stats_table.setItem(i, 1, QTableWidgetItem(value))
            
            routes = self.db.get_probe_routes(active_only=True)
            self.routes_table.setRowCount(len(routes))
            
            for i, route in enumerate(routes):
                data = self.db.get_real_traffic_data(route_id=route['route_id'])
                
                self.routes_table.setItem(i, 0, QTableWidgetItem(route['name']))
                self.routes_table.setItem(i, 1, QTableWidgetItem(str(len(data))))
                
                if data:
                    avg_speed = sum(d['speed_kmh'] for d in data if d['speed_kmh']) / len(data) if data else 0
                    self.routes_table.setItem(i, 2, QTableWidgetItem(f"{avg_speed:.1f} km/h"))
                    status = "✅ Active" if len(data) > 10 else "⚠️ Limited data"
                else:
                    self.routes_table.setItem(i, 2, QTableWidgetItem("-"))
                    status = "❌ No data"
                
                self.routes_table.setItem(i, 3, QTableWidgetItem(status))
        except Exception as e:
            print(f"Error refreshing dashboard: {e}")

    def refresh_scenarios(self):
        """Refresh scenarios table"""
        try:
            cursor = self.db.conn.cursor()
            cursor.execute("""
                SELECT scenario_id, timestamp, mape, r_squared
                FROM validation_metrics
                ORDER BY timestamp DESC
                LIMIT 20
            """)
            
            scenarios = cursor.fetchall()
            self.scenarios_table.setRowCount(len(scenarios))
            
            for i, scenario in enumerate(scenarios):
                self.scenarios_table.setItem(i, 0, QTableWidgetItem(scenario['scenario_id']))
                self.scenarios_table.setItem(i, 1, QTableWidgetItem(scenario['timestamp'][:19]))
                self.scenarios_table.setItem(i, 2, QTableWidgetItem(f"{scenario['mape']:.2f}%"))
                similarity = scenario['r_squared'] * 100 if scenario['r_squared'] else 0
                self.scenarios_table.setItem(i, 3, QTableWidgetItem(f"{similarity:.1f}%"))
                
                status = "✅ Excellent" if scenario['mape'] < 15 else "✓ Good" if scenario['mape'] < 25 else "⚠️ Fair"
                self.scenarios_table.setItem(i, 4, QTableWidgetItem(status))
        except Exception as e:
            print(f"Error refreshing scenarios: {e}")

    # ============== EVENT HANDLERS FOR NEW TABS ==============

    def configure_api_key(self):
        """Configure Google Maps API key"""
        key, ok = QInputDialog.getText(
            self, "Configure API Key",
            "Enter your Google Maps API Key:",
            QLineEdit.EchoMode.Normal,
            self.api_key or ""
        )
        
        if ok and key:
            self.api_key = key
            with open('.env', 'w') as f:
                f.write(f"GOOGLE_MAPS_API_KEY={key}\n")
            self.api_status_label.setText("API Key: ✅ Configured")
            QMessageBox.information(self, "Success", "API key saved successfully!")

    def collect_data_once(self):
        """Collect data once for all routes"""
        if not self.api_key:
            QMessageBox.warning(self, "API Key Required", "Please configure API key first!")
            return
        
        self.collection_status.setText("Collecting...")
        self.worker = DataCollectionWorker(self.api_key)
        self.worker.progress.connect(self.collection_status.setText)
        self.worker.finished.connect(self.on_collection_finished)
        self.worker.start()

    def on_collection_finished(self, results):
        """Handle collection completion"""
        self.collection_status.setText(f"✅ Collected data for {len(results)} routes")
        self.refresh_dashboard()

    def start_continuous_collection(self):
        """Start continuous data collection"""
        QMessageBox.information(
            self, "Continuous Collection",
            "Continuous collection runs in background.\n"
            "This feature is better suited for command-line use.\n"
            "Use: python setup_digital_twin.py (option 3)"
        )

    def stop_continuous_collection(self):
        """Stop continuous collection"""
        pass

    def train_ai_predictor(self):
        """Train AI predictor"""
        try:
            self.ai_training_output.append("Training AI predictor...")
            predictor = SimpleTrafficPredictor(self.db)
            predictor.train_from_historical_data(min_samples=1)
            
            if predictor.trained:
                self.ai_status_label.setText("Status: ✅ Trained")
                self.ai_training_output.append("✅ Training complete!")
                QMessageBox.information(self, "Success", "AI predictor trained successfully!")
            else:
                self.ai_training_output.append("❌ Not enough data for training")
                QMessageBox.warning(self, "Insufficient Data", "Need more data points to train!")
        except Exception as e:
            self.ai_training_output.append(f"❌ Error: {str(e)}")

    def validate_ai_predictor(self):
        """Validate AI predictor"""
        try:
            predictor = SimpleTrafficPredictor(self.db)
            predictor.train_from_historical_data(min_samples=1)
            
            if predictor.trained:
                metrics = predictor.validate_predictions(test_period_hours=168)
                
                if metrics:
                    self.ai_training_output.append(f"\nValidation Results:")
                    self.ai_training_output.append(f"Predictions: {metrics['num_predictions']}")
                    self.ai_training_output.append(f"MAE: {metrics['mae_seconds']:.1f}s")
                    self.ai_training_output.append(f"MAPE: {metrics['mape_percent']:.2f}%")
        except Exception as e:
            self.ai_training_output.append(f"❌ Error: {str(e)}")

    def make_predictions(self):
        """Make traffic predictions"""
        try:
            predictor = SimpleTrafficPredictor(self.db)
            predictor.train_from_historical_data(min_samples=1)
            
            if not predictor.trained:
                QMessageBox.warning(self, "Not Trained", "Train predictor first!")
                return
            
            pred_time = datetime.now().replace(hour=self.pred_hour_spin.value(), minute=0)
            predictions = predictor.predict_all_routes(pred_time)
            
            self.predictions_table.setRowCount(len(predictions))
            
            for i, (route_id, pred) in enumerate(predictions.items()):
                routes = self.db.get_probe_routes()
                route_name = next((r['name'] for r in routes if r['route_id'] == route_id), route_id)
                
                self.predictions_table.setItem(i, 0, QTableWidgetItem(route_name))
                self.predictions_table.setItem(i, 1, QTableWidgetItem(f"{pred['predicted_travel_time']/60:.1f} min"))
                self.predictions_table.setItem(i, 2, QTableWidgetItem(f"{pred['confidence_lower']/60:.1f} min"))
                self.predictions_table.setItem(i, 3, QTableWidgetItem(f"{pred['confidence_upper']/60:.1f} min"))
                self.predictions_table.setItem(i, 4, QTableWidgetItem(str(pred['based_on_samples'])))
        
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Prediction failed: {str(e)}")

    def view_scenario_details(self):
        """View scenario details with visualization"""
        row = self.scenarios_table.currentRow()
        if row >= 0:
            scenario_id = self.scenarios_table.item(row, 0).text()

            try:
                comparison = AreaBasedComparison(self.db)
                results = comparison.compare_area_metrics(scenario_id, "data/logs/edge_state.csv")

                if results:
                    text = f"Scenario: {scenario_id}\n\n"
                    text += f"Speed Error: {results['comparison']['speed_error_pct']:.2f}%\n"
                    text += f"Congestion Similarity: {results['comparison']['congestion_similarity']:.1f}%\n\n"
                    text += f"Real avg speed: {results['real_world']['avg_speed_kmh']:.2f} km/h\n"
                    text += f"Sim avg speed: {results['simulation']['avg_speed_kmh']:.2f} km/h\n"

                    self.comparison_text.setText(text)

                    # Check if visualization exists and offer to open it
                    viz_path = f"data/visualizations/{scenario_id}_overview.png"
                    if os.path.exists(viz_path):
                        text += f"\n\n📊 Visualization available: {viz_path}\n"
                        self.comparison_text.setText(text)

                        # Ask if user wants to open visualization
                        reply = QMessageBox.question(
                            self, "Visualization Available",
                            f"A visualization is available for this scenario.\n\nWould you like to view it?",
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                        )

                        if reply == QMessageBox.StandardButton.Yes:
                            self.open_visualization(viz_path)
                    else:
                        # Offer to generate visualization
                        reply = QMessageBox.question(
                            self, "Generate Visualization",
                            f"No visualization found for this scenario.\n\nWould you like to generate one now?",
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                        )

                        if reply == QMessageBox.StandardButton.Yes:
                            self.generate_visualization(scenario_id)

            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not load scenario: {str(e)}")

    def open_visualization(self, viz_path: str):
        """Open visualization in system default viewer"""
        try:
            import subprocess
            import platform

            system = platform.system()
            if system == 'Windows':
                os.startfile(viz_path)
            elif system == 'Darwin':  # macOS
                subprocess.run(['open', viz_path])
            else:  # Linux
                subprocess.run(['xdg-open', viz_path])

            self.log(f"Opened visualization: {viz_path}", "SUCCESS")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not open visualization: {str(e)}")

    def generate_visualization(self, scenario_id: str):
        """Generate visualization for a scenario"""
        try:
            from modules.advanced_visualizer import AdvancedVisualizer

            self.log(f"Generating visualization for {scenario_id}...", "INFO")
            QApplication.processEvents()

            visualizer = AdvancedVisualizer()
            viz_path = visualizer.plot_simulation_overview(scenario_id)

            self.log(f"✅ Visualization generated: {viz_path}", "SUCCESS")

            # Ask if user wants to open it
            reply = QMessageBox.question(
                self, "Visualization Generated",
                f"Visualization generated successfully!\n\nWould you like to view it now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                self.open_visualization(viz_path)

        except Exception as e:
            self.log(f"❌ Visualization generation failed: {str(e)}", "ERROR")
            QMessageBox.warning(self, "Error", f"Could not generate visualization: {str(e)}")

    def generate_visualization_for_selected(self):
        """Generate visualization for selected scenario"""
        row = self.scenarios_table.currentRow()
        if row >= 0:
            scenario_id = self.scenarios_table.item(row, 0).text()
            self.generate_visualization(scenario_id)
        else:
            QMessageBox.warning(self, "No Selection", "Please select a scenario from the table first.")

    def generate_summary_report(self):
        """Generate summary report for all scenarios"""
        try:
            from modules.results_logger import get_results_logger

            # Get all scenario IDs
            cursor = self.db.conn.cursor()
            cursor.execute("SELECT DISTINCT scenario_id FROM area_comparisons ORDER BY timestamp DESC LIMIT 10")
            scenarios = [row[0] for row in cursor.fetchall()]

            if not scenarios:
                QMessageBox.information(self, "No Data", "No scenarios found to generate report.")
                return

            self.log(f"Generating summary report for {len(scenarios)} scenarios...", "INFO")
            QApplication.processEvents()

            logger = get_results_logger()
            report_path = logger.generate_summary_report(scenarios)

            self.log(f"✅ Summary report generated: {report_path}", "SUCCESS")

            # Ask if user wants to open it
            reply = QMessageBox.question(
                self, "Report Generated",
                f"Summary report generated successfully!\n\nWould you like to view it now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                self.open_visualization(report_path)

        except Exception as e:
            self.log(f"❌ Report generation failed: {str(e)}", "ERROR")
            QMessageBox.warning(self, "Error", f"Could not generate report: {str(e)}")

    def export_results(self):
        """Export results to file"""
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export Results", "results.txt", "Text Files (*.txt);;All Files (*)"
        )

        if filename:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(self.comparison_text.toPlainText())
            QMessageBox.information(self, "Exported", f"Results exported to {filename}")

    # ============== ROUTE ESTIMATION FUNCTIONS ==============

    def run_targeted_simulation(self):
        """Run a simulation with routes targeting the selected origin/destination"""
        import os
        from datetime import datetime, timedelta

        try:
            # Check if points are selected
            if not self.route_origin or not self.route_destination:
                QMessageBox.warning(self, "No Points Selected",
                    "Please select origin and destination points on the map first.")
                return

            # Get network file
            original_network_file, _ = self.find_latest_files()
            if not original_network_file or not os.path.exists(original_network_file):
                QMessageBox.warning(self, "No Network Found",
                    "Please build a network first by going to the Setup tab and clicking 'Build Network'.")
                return

            # Check if using historical data or real-time
            use_historical = self.use_historical_data_check.isChecked()
            validation_time_text = self.validation_time_combo.currentText()

            # Check API key if not using historical data
            if not use_historical and not self.api_key:
                QMessageBox.warning(self, "No API Key",
                    "Please configure your Google Maps API key in the Data Collection tab first.\n\n"
                    "The API key is needed to fetch real-world traffic data for auto-calibration.")
                return

            # Step 1: Get real-world traffic data
            if use_historical:
                # Use stored historical data
                self.route_estimate_text.setPlainText(
                    f"📊 Using stored historical data from database...\n\n"
                    f"Origin: {self.route_origin['lat']:.6f}, {self.route_origin['lon']:.6f}\n"
                    f"Destination: {self.route_destination['lat']:.6f}, {self.route_destination['lon']:.6f}\n"
                    f"Validation Time: {validation_time_text}\n"
                )
                QApplication.processEvents()

                try:
                    # Query database for historical data matching this route area
                    real_data = self._get_historical_route_data(
                        self.route_origin,
                        self.route_destination,
                        validation_time_text
                    )

                    if not real_data:
                        QMessageBox.warning(self, "No Historical Data",
                            f"No stored data found for this route and time period.\n\n"
                            f"Please collect data first using:\n"
                            f"- collect_typical_network_traffic.py\n"
                            f"- Or uncheck 'Use stored historical data' to fetch real-time data")
                        return

                except Exception as e:
                    QMessageBox.critical(self, "Error",
                        f"Failed to retrieve historical data: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    return
            else:
                # Fetch real-time traffic data from Google Maps
                self.route_estimate_text.setPlainText(
                    f"🌐 Fetching real-time traffic data from Google Maps...\n\n"
                    f"Origin: {self.route_origin['lat']:.6f}, {self.route_origin['lon']:.6f}\n"
                    f"Destination: {self.route_destination['lat']:.6f}, {self.route_destination['lon']:.6f}\n"
                    f"Validation Time: {validation_time_text}\n"
                )
                QApplication.processEvents()

                from modules.data_collector import TrafficDataCollector

                collector = TrafficDataCollector(self.api_key)

                try:
                    # Determine departure time based on selection
                    if validation_time_text == "Current time (real-time traffic)":
                        # Use current time
                        real_data = collector.fetch_route_traffic(
                            origin_lat=self.route_origin['lat'],
                            origin_lon=self.route_origin['lon'],
                            dest_lat=self.route_destination['lat'],
                            dest_lon=self.route_destination['lon'],
                            route_id=None
                        )
                    else:
                        # Use typical time from selection
                        departure_time = self._parse_validation_time(validation_time_text)
                        real_data = self._fetch_typical_traffic(
                            collector,
                            self.route_origin['lat'],
                            self.route_origin['lon'],
                            self.route_destination['lat'],
                            self.route_destination['lon'],
                            departure_time
                        )

                    if not real_data or 'speed_kmh' not in real_data:
                        QMessageBox.warning(self, "API Error",
                            "Could not fetch traffic data from Google Maps.\n"
                            "Please check your API key and internet connection.")
                        return

                except Exception as e:
                    QMessageBox.critical(self, "Error",
                        f"Failed to fetch Google Maps data: {str(e)}\n\n"
                        f"Please check your API key and internet connection.")
                    import traceback
                    traceback.print_exc()
                    return

            # Extract data (works for both historical and real-time)
            real_world_speed = real_data['speed_kmh']
            real_travel_time = real_data['travel_time_seconds']
            real_distance = real_data['distance_meters'] / 1000.0  # Convert to km

            # Step 2: Auto-calculate optimal simulation parameters based on real traffic
            # Vehicle count based on congestion level
            if real_world_speed < 25:
                num_vehicles = 150  # Severe congestion
                congestion_desc = "SEVERE CONGESTION (gridlock)"
            elif real_world_speed < 35:
                num_vehicles = 120  # Heavy congestion
                congestion_desc = "HEAVY CONGESTION"
            elif real_world_speed < 45:
                num_vehicles = 80  # Moderate congestion (typical Cairo)
                congestion_desc = "MODERATE CONGESTION"
            elif real_world_speed < 55:
                num_vehicles = 50  # Light congestion
                congestion_desc = "LIGHT CONGESTION"
            else:
                num_vehicles = 30  # Free flow
                congestion_desc = "FREE FLOW"

            # Simulation duration: 3x real travel time to ensure enough data collection
            # Minimum 10 minutes, maximum 30 minutes
            sim_duration = max(600, min(1800, int(real_travel_time * 3)))

            self.route_estimate_text.append(
                f"\n✅ Traffic Data Retrieved:\n"
                f"   Source: {'Historical Database' if use_historical else 'Google Maps API'}\n"
                f"   Distance: {real_distance:.2f} km\n"
                f"   Travel Time: {real_travel_time/60:.1f} minutes\n"
                f"   Average Speed: {real_world_speed:.1f} km/h\n"
                f"   Traffic Level: {congestion_desc}\n\n"
                f"📊 Auto-Calculated Simulation Parameters:\n"
                f"   Vehicles: {num_vehicles} (based on congestion)\n"
                f"   Duration: {sim_duration}s ({sim_duration/60:.1f} min)\n"
            )
            QApplication.processEvents()

            # Step 3: Show confirmation dialog with auto-calculated values (allow override)
            from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QSpinBox, QDialogButtonBox

            dialog = QDialog(self)
            dialog.setWindowTitle("Confirm Simulation Parameters")
            dialog_layout = QVBoxLayout(dialog)

            dialog_layout.addWidget(QLabel(
                f"📊 Auto-calculated parameters based on real-world traffic:\n\n"
                f"Real-world conditions:\n"
                f"  • Speed: {real_world_speed:.1f} km/h ({congestion_desc})\n"
                f"  • Travel time: {real_travel_time/60:.1f} minutes\n"
                f"  • Distance: {real_distance:.2f} km\n\n"
                f"You can adjust if needed:"
            ))

            dialog_layout.addWidget(QLabel("\nNumber of vehicles:"))
            num_vehicles_spin = QSpinBox()
            num_vehicles_spin.setRange(10, 200)
            num_vehicles_spin.setValue(num_vehicles)
            num_vehicles_spin.setToolTip(f"Auto-calculated from traffic level ({congestion_desc})")
            dialog_layout.addWidget(num_vehicles_spin)

            dialog_layout.addWidget(QLabel("\nSimulation duration (seconds):"))
            duration_spin = QSpinBox()
            duration_spin.setRange(300, 3600)
            duration_spin.setValue(sim_duration)
            duration_spin.setToolTip("Auto-calculated: 3x real travel time for data collection")
            dialog_layout.addWidget(duration_spin)

            button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
            button_box.accepted.connect(dialog.accept)
            button_box.rejected.connect(dialog.reject)
            dialog_layout.addWidget(button_box)

            if dialog.exec() != QDialog.DialogCode.Accepted:
                return

            num_vehicles = num_vehicles_spin.value()
            sim_duration = duration_spin.value()

            # Update UI
            self.route_estimate_text.append(
                f"\n🎯 Starting targeted simulation...\n"
                f"Vehicles: {num_vehicles}\n"
                f"Duration: {sim_duration}s ({sim_duration/60:.1f} minutes)\n\n"
                f"🧹 Clearing old simulation data..."
            )
            QApplication.processEvents()

            # Clear old simulation data to ensure clean calibration
            edge_log = "data/logs/edge_state.csv"
            if os.path.exists(edge_log):
                try:
                    os.remove(edge_log)
                    self.route_estimate_text.append(f"✅ Old data cleared\n\n")
                    print("[TARGETED_SIM] Cleared old edge_state.csv")
                except Exception as e:
                    print(f"[TARGETED_SIM] Warning: Could not clear old data: {e}")
                    self.route_estimate_text.append(f"⚠️ Could not clear old data\n\n")

            # Calculate Cairo parameters based on real-world speed
            from modules.traffic_configurator import TrafficConfigurator
            from modules.network_calibrator import calibrate_network_speeds

            configurator = TrafficConfigurator()
            cairo_params = configurator.configure_cairo_parameters(avg_speed_kmh=real_world_speed)

            self.route_estimate_text.append(
                f"📊 Calibrating network to real-world speeds...\n"
                f"   Target speed: {real_world_speed:.1f} km/h\n"
            )
            QApplication.processEvents()

            # CRITICAL: Calibrate network edge speeds to match real-world traffic
            # Create calibrated network with realistic speed limits
            calibrated_network_file = original_network_file.replace('.net.xml', '_calibrated.net.xml')
            try:
                calibrate_network_speeds(
                    network_file=original_network_file,
                    target_speed_kmh=real_world_speed,
                    output_file=calibrated_network_file
                )
                network_file = calibrated_network_file  # Use calibrated network

                self.route_estimate_text.append(
                    f"✅ Network calibrated successfully!\n"
                    f"   Speed limits adjusted to match real-world conditions\n\n"
                    f"📊 Vehicle parameters calculated:\n"
                    f"   Speed factor: {cairo_params['speedFactor']:.2f}\n\n"
                    f"Generating calibrated routes..."
                )
            except Exception as e:
                print(f"[TARGETED_SIM] Warning: Network calibration failed: {e}")
                network_file = original_network_file  # Fallback to original
                self.route_estimate_text.append(
                    f"⚠️ Network calibration failed, using original network\n\n"
                    f"Generating routes..."
                )

            QApplication.processEvents()

            # Generate targeted routes WITH calibration parameters
            route_file = generate_targeted_routes(
                network_file,
                os.path.join("data", "routes"),
                self.route_origin['lat'],
                self.route_origin['lon'],
                self.route_destination['lat'],
                self.route_destination['lon'],
                sim_time=sim_duration,
                num_vehicles=num_vehicles,
                calibration_params=cairo_params  # Pass calibration to route generation!
            )

            if not route_file:
                QMessageBox.critical(self, "Route Generation Failed",
                    "Could not generate routes for the selected points. "
                    "Make sure the points are within the simulated network area.")
                return

            self.route_estimate_text.append(f"✅ Routes generated\n\nCreating simulation config...")
            QApplication.processEvents()

            # Create simulation config
            cfg_path = create_config(
                network_file,
                route_file,
                os.path.join("data", "configs", "targeted_simulation.sumocfg"),
                sim_time=sim_duration
            )

            self.route_estimate_text.append(f"✅ Config created\n\n🚗 Running calibrated simulation...")
            QApplication.processEvents()

            # Use calibration parameters already calculated earlier
            scenario_id = f"targeted_route_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

            print(f"[TARGETED_SIM] Using real-world calibrated parameters")
            print(f"[TARGETED_SIM] Real-world speed: {real_world_speed:.1f} km/h")
            print(f"[TARGETED_SIM] Speed factor: {cairo_params['speedFactor']:.2f}")

            run_simulation(
                cfg_path,
                gui=True,
                scenario_id=scenario_id,
                enable_digital_twin=True,
                enable_dynamic_calibration=True,  # Enable real-time calibration
                initial_params=cairo_params  # Use real-world calibrated parameters
            )

            self.route_estimate_text.append(
                f"\n✅ Simulation completed!\n\n"
                f"Data has been collected for your selected route.\n"
                f"Now click '📍 Estimate Travel Time' to get accurate results!"
            )

            QMessageBox.information(self, "Simulation Complete",
                "Targeted simulation finished!\n\n"
                "Your selected route now has traffic data.\n"
                "Click 'Estimate Travel Time' to see the results.")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Targeted simulation failed: {e}")
            import traceback
            traceback.print_exc()

    def _parse_validation_time(self, time_text: str):
        """Parse validation time selection to datetime"""
        from datetime import datetime, timedelta

        # Map day names to weekday numbers
        day_map = {
            'Monday': 0, 'Tuesday': 1, 'Wednesday': 2, 'Thursday': 3,
            'Friday': 4, 'Saturday': 5, 'Sunday': 6
        }

        # Extract day and time from text like "Monday 8:00 AM (typical)"
        parts = time_text.split()
        day_name = parts[0]
        time_str = parts[1]  # e.g., "8:00"

        # Parse hour
        hour = int(time_str.split(':')[0])
        if 'PM' in time_text and hour != 12:
            hour += 12
        elif 'AM' in time_text and hour == 12:
            hour = 0

        # Calculate next occurrence of this day/time
        now = datetime.now()
        target_weekday = day_map[day_name]
        days_ahead = (target_weekday - now.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7  # Next week

        target_date = now + timedelta(days=days_ahead)
        target_date = target_date.replace(hour=hour, minute=0, second=0, microsecond=0)

        return target_date

    def _fetch_typical_traffic(self, collector, origin_lat, origin_lon, dest_lat, dest_lon, departure_time):
        """Fetch typical traffic from Google Maps for a specific time"""
        import requests
        import time as time_module

        origin = f"{origin_lat},{origin_lon}"
        destination = f"{dest_lat},{dest_lon}"
        departure_timestamp = int(departure_time.timestamp())

        params = {
            'origin': origin,
            'destination': destination,
            'mode': 'driving',
            'departure_time': departure_timestamp,
            'key': collector.api_key
        }

        # Rate limiting
        time_module.sleep(1.0)

        response = requests.get(
            "https://maps.googleapis.com/maps/api/directions/json",
            params=params,
            timeout=10
        )
        response.raise_for_status()
        data = response.json()

        if data['status'] != 'OK':
            raise Exception(f"API Error: {data['status']}")

        route = data['routes'][0]['legs'][0]
        distance_meters = route['distance']['value']

        # Use duration_in_traffic for typical traffic
        if 'duration_in_traffic' in route:
            travel_time = route['duration_in_traffic']['value']
        else:
            travel_time = route['duration']['value']

        speed_kmh = (distance_meters / 1000) / (travel_time / 3600) if travel_time > 0 else 0

        return {
            'travel_time_seconds': travel_time,
            'distance_meters': distance_meters,
            'speed_kmh': round(speed_kmh, 2),
            'raw_response': data
        }

    def _get_historical_route_data(self, origin, destination, validation_time_text):
        """Query database for historical data near this route"""
        from datetime import datetime, timedelta
        import math

        # Parse the selected time to get day/hour filter
        if validation_time_text == "Current time (real-time traffic)":
            # Use current day/hour
            now = datetime.now()
            target_day = now.strftime('%A').lower()
            target_hour = now.hour
        else:
            # Parse from selection like "Monday 8:00 AM (typical)"
            parts = validation_time_text.split()
            target_day = parts[0].lower()
            time_str = parts[1]
            hour = int(time_str.split(':')[0])
            if 'PM' in validation_time_text and hour != 12:
                hour += 12
            elif 'AM' in validation_time_text and hour == 12:
                hour = 0
            target_hour = hour

        # Get all traffic data from database
        all_data = self.db.get_real_traffic_data()

        if not all_data:
            return None

        # Filter data:
        # 1. Find routes near our origin/destination
        # 2. Filter by matching day/hour

        matching_routes = []
        for record in all_data:
            # Check if timestamp matches target day/hour
            timestamp = datetime.fromisoformat(record['timestamp'])
            record_day = timestamp.strftime('%A').lower()
            record_hour = timestamp.hour

            # Match day and hour (within ±1 hour tolerance)
            if record_day == target_day and abs(record_hour - target_hour) <= 1:
                matching_routes.append(record)

        if not matching_routes:
            return None

        # Calculate average from matching records
        avg_speed = sum(r['speed_kmh'] for r in matching_routes if r['speed_kmh']) / len(matching_routes)
        avg_time = sum(r['travel_time_seconds'] for r in matching_routes) / len(matching_routes)
        avg_distance = sum(r['distance_meters'] for r in matching_routes) / len(matching_routes)

        return {
            'speed_kmh': round(avg_speed, 2),
            'travel_time_seconds': int(avg_time),
            'distance_meters': int(avg_distance),
            'sample_count': len(matching_routes)
        }

    def estimate_route_time(self):
        """Estimate travel time between two points using simulation data"""
        import os
        try:
            # Check if points are selected
            if not self.route_origin or not self.route_destination:
                QMessageBox.warning(self, "No Points Selected",
                    "Please click on the map to select origin (green) and destination (red) points first.")
                return

            # Get coordinates from selected points
            from_lat = self.route_origin['lat']
            from_lon = self.route_origin['lon']
            to_lat = self.route_destination['lat']
            to_lon = self.route_destination['lon']

            # Get latest network file
            net_file, _ = self.find_latest_files()
            if not net_file:
                QMessageBox.warning(self, "No Network",
                    "No network file found. Please run a simulation first.")
                return

            # Get latest scenario ID from simulation results
            cursor = self.db.conn.cursor()
            cursor.execute("SELECT DISTINCT scenario_id FROM simulation_results ORDER BY timestamp DESC LIMIT 1")
            result = cursor.fetchone()
            if not result:
                # Try calibration_params table
                cursor.execute("SELECT DISTINCT scenario_id FROM calibration_params ORDER BY timestamp DESC LIMIT 1")
                result = cursor.fetchone()
            scenario_id = result['scenario_id'] if result else "latest_simulation"

            self.route_estimate_text.setText("🔄 Calculating route...")
            QApplication.processEvents()

            # Create estimator and find route
            from modules.route_estimator import RouteEstimator
            estimator = RouteEstimator(net_file, scenario_id)

            result = estimator.find_route(from_lat, from_lon, to_lat, to_lon)

            if not result or not result.get('success'):
                self.route_estimate_text.setText(
                    "❌ Could not find a route between these points.\n"
                    "Make sure both points are within the simulated area and on valid roads."
                )
                return

            # Check if data is uncalibrated (speeds too high = old data)
            avg_speed = result['average_speed_kmh']
            if avg_speed > 70:
                # Uncalibrated data detected!
                from PyQt6.QtWidgets import QMessageBox
                reply = QMessageBox.warning(
                    self,
                    "⚠️ Uncalibrated Simulation Data Detected",
                    f"The simulation data shows unrealistic speeds ({avg_speed:.1f} km/h).\n\n"
                    f"This means you're using OLD simulation data from before calibration was added.\n\n"
                    f"What you need to do:\n"
                    f"1. Delete old simulation data (edge_state.csv)\n"
                    f"2. Run a NEW 'Targeted Simulation' with your selected route\n"
                    f"3. The new simulation will be calibrated to match real-world speeds\n\n"
                    f"Would you like me to clear the old data now?\n"
                    f"(You'll need to run a new simulation after this)",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.Yes
                )

                if reply == QMessageBox.StandardButton.Yes:
                    # Clear old simulation data
                    edge_log = "data/logs/edge_state.csv"
                    if os.path.exists(edge_log):
                        try:
                            os.remove(edge_log)
                            QMessageBox.information(
                                self,
                                "Data Cleared",
                                "✅ Old simulation data has been deleted.\n\n"
                                "Now click 'Run Targeted Simulation' to generate new calibrated data."
                            )
                            self.route_estimate_text.setText(
                                "⚠️ Old uncalibrated data has been cleared.\n\n"
                                "Please run a NEW 'Targeted Simulation' to generate calibrated data:\n"
                                "1. Select origin and destination on map (already done ✓)\n"
                                "2. Click 'Run Targeted Simulation' button\n"
                                "3. System will fetch Google Maps data and calibrate automatically\n"
                                "4. Then click 'Estimate Travel Time' again"
                            )
                            return
                        except Exception as e:
                            QMessageBox.critical(self, "Error", f"Could not delete old data: {e}")
                    else:
                        QMessageBox.information(
                            self,
                            "No Old Data",
                            "No old edge_state.csv found.\n\n"
                            "Please run 'Targeted Simulation' to generate new data."
                        )
                        return

            # Format results
            text = "=" * 60 + "\n"
            text += "📍 ROUTE ESTIMATION (Based on Simulation Data)\n"
            text += "=" * 60 + "\n\n"

            text += f"Origin:      {from_lat:.6f}, {from_lon:.6f}\n"
            text += f"Destination: {to_lat:.6f}, {to_lon:.6f}\n\n"

            text += "🚗 ESTIMATED TRAVEL:\n"
            text += f"  Distance:     {result['distance_km']:.2f} km\n"
            text += f"  Travel Time:  {int(result['travel_time_minutes'])} min {int((result['travel_time_minutes'] % 1) * 60)} sec\n"
            text += f"  Avg Speed:    {result['average_speed_kmh']:.1f} km/h\n\n"

            text += "📊 ROUTE DETAILS:\n"
            text += f"  Number of edges:     {result['num_edges']}\n"
            text += f"  Edges with sim data: {result['edges_with_sim_data']} ({result['data_coverage']:.1f}%)\n"
            text += f"  Route factor:        {result['route_factor']:.2f}x (vs straight line)\n\n"

            if result['data_coverage'] < 80:
                text += "⚠️ Note: Less than 80% of route has simulation data.\n"
                text += "   Some speeds estimated using defaults.\n\n"

            text += "💡 Tip: Compare with Google Maps to see accuracy!\n"

            self.route_estimate_text.setText(text)
            self.log(f"Route estimated: {result['distance_km']:.2f} km in {result['travel_time_minutes']:.1f} min", "SUCCESS")

        except Exception as e:
            self.route_estimate_text.setText(f"❌ Error: {str(e)}")
            self.log(f"Route estimation error: {str(e)}", "ERROR")
            import traceback
            traceback.print_exc()

    def compare_route_with_google(self):
        """Compare simulation estimate with Google Maps real-time data"""
        try:
            # Check if points are selected
            if not self.route_origin or not self.route_destination:
                QMessageBox.warning(self, "No Points Selected",
                    "Please click on the map to select origin (green) and destination (red) points first.")
                return

            # Check API key
            if not self.api_key:
                QMessageBox.warning(self, "No API Key",
                    "Please configure your Google Maps API key in the Data Collection tab first.")
                return

            # Get coordinates from selected points
            from_lat = self.route_origin['lat']
            from_lon = self.route_origin['lon']
            to_lat = self.route_destination['lat']
            to_lon = self.route_destination['lon']

            # Get latest network file
            net_file, _ = self.find_latest_files()
            if not net_file:
                QMessageBox.warning(self, "No Network",
                    "No network file found. Please run a simulation first.")
                return

            # Get latest scenario ID from simulation results
            cursor = self.db.conn.cursor()
            cursor.execute("SELECT DISTINCT scenario_id FROM simulation_results ORDER BY timestamp DESC LIMIT 1")
            result = cursor.fetchone()
            if not result:
                # Try calibration_params table
                cursor.execute("SELECT DISTINCT scenario_id FROM calibration_params ORDER BY timestamp DESC LIMIT 1")
                result = cursor.fetchone()
            scenario_id = result['scenario_id'] if result else "latest_simulation"

            self.route_estimate_text.setText("🔄 Fetching Google Maps data and calculating route...")
            QApplication.processEvents()

            # Create estimator and compare
            from modules.route_estimator import RouteEstimator
            estimator = RouteEstimator(net_file, scenario_id)

            result = estimator.compare_with_google_maps(from_lat, from_lon, to_lat, to_lon, self.api_key)

            if not result or not result.get('success'):
                self.route_estimate_text.setText(
                    "❌ Could not find a route between these points.\n"
                    "Make sure both points are within the simulated area and on valid roads."
                )
                return

            # Format comparison results
            text = "=" * 60 + "\n"
            text += "🌐 ROUTE ESTIMATION vs GOOGLE MAPS COMPARISON\n"
            text += "=" * 60 + "\n\n"

            text += f"Origin:      {from_lat:.6f}, {from_lon:.6f}\n"
            text += f"Destination: {to_lat:.6f}, {to_lon:.6f}\n\n"

            # Simulation results
            text += "🖥️ SIMULATION ESTIMATE:\n"
            text += f"  Distance:     {result['distance_km']:.2f} km\n"
            text += f"  Travel Time:  {int(result['travel_time_minutes'])} min {int((result['travel_time_minutes'] % 1) * 60)} sec\n"
            text += f"  Avg Speed:    {result['average_speed_kmh']:.1f} km/h\n\n"

            # Google Maps results
            if 'google_maps' in result:
                gm = result['google_maps']
                text += "🌐 GOOGLE MAPS (Real-time):\n"
                text += f"  Distance:     {gm['distance_meters'] / 1000:.2f} km\n"
                text += f"  Travel Time:  {int(gm['travel_time_minutes'])} min {int((gm['travel_time_minutes'] % 1) * 60)} sec\n"
                text += f"  Avg Speed:    {gm['speed_kmh']:.1f} km/h\n"
                if gm['traffic_delay_seconds'] > 0:
                    text += f"  Traffic Delay: {int(gm['traffic_delay_seconds'] / 60)} min\n"
                text += "\n"

                # Accuracy comparison
                if 'comparison' in result:
                    comp = result['comparison']
                    text += "📊 ACCURACY:\n"
                    text += f"  Time Error:   {comp['time_error_seconds']:.0f} sec ({comp['time_error_percent']:.1f}%)\n"
                    text += f"  Speed Error:  {comp['speed_error_kmh']:.1f} km/h ({comp['speed_error_percent']:.1f}%)\n"
                    text += f"  Distance Err: {comp['distance_error_meters']:.0f} m\n\n"

                    # Verdict
                    if comp['time_error_percent'] < 10:
                        text += "✅ EXCELLENT accuracy! Digital twin closely matches reality.\n"
                    elif comp['time_error_percent'] < 20:
                        text += "✔️ GOOD accuracy. Minor differences from real traffic.\n"
                    elif comp['time_error_percent'] < 30:
                        text += "⚠️ MODERATE accuracy. Some differences from real traffic.\n"
                    else:
                        text += "❌ Needs calibration. Consider running more simulations.\n"
            else:
                text += "⚠️ Could not fetch Google Maps data for comparison.\n"

            text += "\n" + "=" * 60 + "\n"
            text += f"Data coverage: {result['data_coverage']:.1f}% of route edges\n"

            self.route_estimate_text.setText(text)
            self.log(f"Route compared: {result.get('comparison', {}).get('time_error_percent', 0):.1f}% error", "SUCCESS")

        except Exception as e:
            self.route_estimate_text.setText(f"❌ Error: {str(e)}")
            self.log(f"Route comparison error: {str(e)}", "ERROR")
            import traceback
            traceback.print_exc()

    def find_latest_files(self):
        """Find latest network and route files, or use selected cached network"""
        net_dir = "data/networks"
        route_dir = "data/routes"

        network_file = None
        route_file = None

        # If a specific network was selected from cache, use that
        if self.selected_network_file and os.path.exists(self.selected_network_file):
            network_file = self.selected_network_file
            print(f"[DEBUG] Using selected cached network: {network_file}")
        elif os.path.exists(net_dir):
            # Otherwise, get the latest network file
            files = [f for f in os.listdir(net_dir) if f.endswith('.net.xml')]
            if files:
                files.sort(key=lambda x: os.path.getmtime(os.path.join(net_dir, x)))
                network_file = os.path.join(net_dir, files[-1])
                print(f"[DEBUG] Using latest network file: {network_file}")

        if os.path.exists(route_dir):
            files = [f for f in os.listdir(route_dir) if f.endswith('.rou.xml')]
            if files:
                files.sort(key=lambda x: os.path.getmtime(os.path.join(route_dir, x)))
                route_file = os.path.join(route_dir, files[-1])

        return network_file, route_file

    # ============== ROUTE ESTIMATION MAP FUNCTIONS ==============

    def init_route_map(self, center=None, zoom=12):
        """Initialize the route estimation map with click handlers"""
        try:
            # Get actual network bounds from the network file
            network_file, _ = self.find_latest_files()
            actual_bbox = None

            if network_file and os.path.exists(network_file):
                import xml.etree.ElementTree as ET
                try:
                    tree = ET.parse(network_file)
                    root = tree.getroot()
                    location = root.find('location')
                    if location is not None:
                        orig_boundary = location.get('origBoundary')
                        if orig_boundary:
                            # Parse: "west,south,east,north"
                            bounds = orig_boundary.split(',')
                            if len(bounds) == 4:
                                actual_bbox = {
                                    'west': float(bounds[0]),
                                    'south': float(bounds[1]),
                                    'east': float(bounds[2]),
                                    'north': float(bounds[3])
                                }
                                print(f"[DEBUG] Read network bounds from file: {actual_bbox}")
                except Exception as e:
                    print(f"[DEBUG] Could not read network bounds: {e}")

            # Use actual network bounds if available
            if actual_bbox:
                center_lat = (actual_bbox['north'] + actual_bbox['south']) / 2
                center_lon = (actual_bbox['east'] + actual_bbox['west']) / 2
                center = [center_lat, center_lon]
                zoom = 13
                print(f"[DEBUG] Using actual network center: {center}")
            elif self.selected_bbox:
                center_lat = (self.selected_bbox['north'] + self.selected_bbox['south']) / 2
                center_lon = (self.selected_bbox['east'] + self.selected_bbox['west']) / 2
                center = [center_lat, center_lon]
                zoom = 13
                print(f"[DEBUG] Using simulated area center: {center}")
            elif center is None:
                center = [30.0444, 31.2357]
                print(f"[DEBUG] Using default Cairo center: {center}")

            print(f"[DEBUG] Creating folium map at {center} with zoom {zoom}")
            m = folium.Map(
                location=center,
                zoom_start=zoom,
                tiles='OpenStreetMap',
                control_scale=True
            )

            # Add network boundary rectangle if available
            if actual_bbox:
                folium.Rectangle(
                    bounds=[
                        [actual_bbox['south'], actual_bbox['west']],
                        [actual_bbox['north'], actual_bbox['east']]
                    ],
                    color='blue',
                    fill=True,
                    fillColor='lightblue',
                    fillOpacity=0.2,
                    weight=2,
                    popup='Network Boundary - Click inside this area',
                    tooltip='Simulated Network Area'
                ).add_to(m)

            # Add a note to click on the map
            folium.Marker(
                center,
                popup='Click anywhere INSIDE THE BLUE AREA to select origin and destination',
                icon=folium.Icon(color='blue', icon='info-sign'),
                tooltip='Click inside the blue area to start'
            ).add_to(m)

            map_file = "route_map.html"
            print(f"[DEBUG] Saving route map to {map_file}")
            m.save(map_file)

            file_path = os.path.abspath(map_file)
            print(f"[DEBUG] Map saved to: {file_path}")
            print(f"[DEBUG] File exists: {os.path.exists(file_path)}")

            url = QUrl.fromLocalFile(file_path)
            print(f"[DEBUG] Loading URL: {url.toString()}")
            self.route_map_view.setUrl(url)
            print(f"[DEBUG] Route map initialized at {center} with zoom {zoom}")

        except Exception as e:
            print(f"[ERROR] Failed to initialize route map: {e}")
            import traceback
            traceback.print_exc()

    def on_route_map_loaded(self, ok):
        """Called when route map finishes loading"""
        print(f"[DEBUG] Route map loaded (success={ok}), injecting qwebchannel.js and click handler...")

        if not ok:
            print("[ERROR] Route map failed to load!")
            return

        # Load qwebchannel.js dynamically first
        load_qwebchannel = """
        (function() {
            if (typeof QWebChannel === 'undefined') {
                var script = document.createElement('script');
                script.src = 'qrc:///qtwebchannel/qwebchannel.js';
                script.onload = function() { console.log('[ROUTE_MAP] qwebchannel.js loaded'); };
                script.onerror = function() { console.log('[ROUTE_MAP ERROR] Failed to load qwebchannel.js'); };
                document.head.appendChild(script);
            }
        })();
        """
        self.route_map_view.page().runJavaScript(load_qwebchannel)

        # Then inject JavaScript with retry mechanism to wait for libraries to load
        js_code = """
        (function() {
            var attempts = 0;
            var maxAttempts = 200;  // Increased to 10 seconds

            function setupMapClickHandler() {
                attempts++;

                // Debug: Show what's available
                if (attempts === 1) {
                    console.log('[ROUTE_MAP] Checking for map object...');
                    console.log('[ROUTE_MAP] Window keys:', Object.keys(window).filter(k => k.includes('map') || k.includes('Map')));
                }

                // Check if QWebChannel is available
                if (typeof QWebChannel === 'undefined') {
                    if (attempts < maxAttempts) {
                        setTimeout(setupMapClickHandler, 50);
                    } else {
                        console.log('[ROUTE_MAP ERROR] QWebChannel not loaded after ' + maxAttempts + ' attempts');
                    }
                    return;
                }

                // Try to find the map object - Folium creates it with a unique ID
                var foundMap = null;

                // Method 1: Check for 'map' variable
                if (typeof map !== 'undefined') {
                    foundMap = map;
                    console.log('[ROUTE_MAP] Found map via global "map" variable');
                }

                // Method 2: Search for Leaflet map instances
                if (!foundMap && typeof L !== 'undefined' && L.DomUtil) {
                    var mapDivs = document.querySelectorAll('[id^="map"]');
                    for (var i = 0; i < mapDivs.length; i++) {
                        if (mapDivs[i]._leaflet_id) {
                            // Found a Leaflet map div
                            var mapId = mapDivs[i]._leaflet_id;
                            // Try to get the map instance
                            for (var key in window) {
                                if (window[key] && window[key]._container === mapDivs[i]) {
                                    foundMap = window[key];
                                    console.log('[ROUTE_MAP] Found map via Leaflet container search');
                                    break;
                                }
                            }
                        }
                    }
                }

                if (!foundMap) {
                    if (attempts < maxAttempts) {
                        setTimeout(setupMapClickHandler, 50);
                    } else {
                        console.log('[ROUTE_MAP ERROR] Map object not found after ' + maxAttempts + ' attempts');
                        console.log('[ROUTE_MAP ERROR] Available window keys:', Object.keys(window).slice(0, 20));
                    }
                    return;
                }

                // Both QWebChannel and map exist, setup the bridge
                if (typeof window.qt !== 'undefined' && typeof window.qt.webChannelTransport !== 'undefined') {
                    new QWebChannel(window.qt.webChannelTransport, function(channel) {
                        window.routeBridge = channel.objects.bridge;
                        console.log('[ROUTE_MAP] ✅ Bridge connected after ' + attempts + ' attempts');

                        // Add click handler to map
                        foundMap.on('click', function(e) {
                            var lat = e.latlng.lat;
                            var lon = e.latlng.lng;
                            console.log('[ROUTE_MAP] 🗺️ Map clicked at: ' + lat + ', ' + lon);
                            window.routeBridge.receivePoint(lat, lon);
                        });
                        console.log('[ROUTE_MAP] ✅ Click handler registered successfully');
                    });
                } else {
                    console.log('[ROUTE_MAP ERROR] Qt WebChannel transport not available');
                }
            }

            // Start checking after a small delay to let page settle
            setTimeout(setupMapClickHandler, 100);
        })();
        """

        self.route_map_view.page().runJavaScript(js_code)
        print("[DEBUG] JavaScript injected for route map")

    def on_route_point_selected(self, lat, lon):
        """Handle point selection from map"""
        print(f"[ROUTE] Point selected: {lat}, {lon}")

        if self.route_origin is None:
            # First click - set origin
            self.route_origin = {'lat': lat, 'lon': lon}
            self.route_selection_label.setText(
                f"✅ Origin selected: {lat:.6f}, {lon:.6f}\n"
                f"👉 Now click on the map to select your destination (will appear in RED)"
            )
            self.route_selection_label.setStyleSheet("padding: 10px; background: #C8E6C9; border-radius: 5px; font-size: 10pt;")

            # Add green marker to map
            self.update_route_map()

        elif self.route_destination is None:
            # Second click - set destination
            self.route_destination = {'lat': lat, 'lon': lon}
            self.route_selection_label.setText(
                f"✅ Route ready!\n"
                f"🟢 Origin: {self.route_origin['lat']:.6f}, {self.route_origin['lon']:.6f}\n"
                f"🔴 Destination: {lat:.6f}, {lon:.6f}\n"
                f"👉 Click 'Estimate Travel Time' to get results!"
            )
            self.route_selection_label.setStyleSheet("padding: 10px; background: #BBDEFB; border-radius: 5px; font-size: 10pt; font-weight: bold;")

            # Add both markers and line to map
            self.update_route_map()

        else:
            # Both already selected - clear and start over
            self.clear_route_selection()
            self.on_route_point_selected(lat, lon)  # Treat this as new origin

    def update_route_map(self):
        """Update the route map with selected points"""
        # Get center point
        if self.selected_bbox:
            center_lat = (self.selected_bbox['north'] + self.selected_bbox['south']) / 2
            center_lon = (self.selected_bbox['east'] + self.selected_bbox['west']) / 2
        else:
            center_lat = 30.0444
            center_lon = 31.2357

        m = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=13,
            tiles='OpenStreetMap',
            control_scale=True
        )

        # Add origin marker (green)
        if self.route_origin:
            folium.Marker(
                [self.route_origin['lat'], self.route_origin['lon']],
                popup='Origin',
                icon=folium.Icon(color='green', icon='play', prefix='fa'),
                tooltip='Start Point'
            ).add_to(m)

        # Add destination marker (red)
        if self.route_destination:
            folium.Marker(
                [self.route_destination['lat'], self.route_destination['lon']],
                popup='Destination',
                icon=folium.Icon(color='red', icon='stop', prefix='fa'),
                tooltip='End Point'
            ).add_to(m)

            # Add line between points
            folium.PolyLine(
                [[self.route_origin['lat'], self.route_origin['lon']],
                 [self.route_destination['lat'], self.route_destination['lon']]],
                color='blue',
                weight=3,
                opacity=0.7
            ).add_to(m)

        m.save("route_map.html")
        url = QUrl.fromLocalFile(os.path.abspath("route_map.html"))
        self.route_map_view.setUrl(url)

    def clear_route_selection(self):
        """Clear selected route points"""
        self.route_origin = None
        self.route_destination = None
        self.route_selection_label.setText("❓ No points selected yet. Click on the map to select origin and destination.")
        self.route_selection_label.setStyleSheet("padding: 10px; background: #FFF3E0; border-radius: 5px; font-size: 10pt;")
        self.route_estimate_text.clear()

        # Refresh map
        self.update_route_map()

    # ============== ROUTE SELECTION EVENT HANDLERS ==============

    def save_route(self, route_num):
        """Save a specific route to database"""
        try:
            # Find the widgets by object name
            route_name = self.findChild(QLineEdit, f"route_name_{route_num}").text()
            origin_lat = self.findChild(QDoubleSpinBox, f"origin_lat_{route_num}").value()
            origin_lon = self.findChild(QDoubleSpinBox, f"origin_lon_{route_num}").value()
            dest_lat = self.findChild(QDoubleSpinBox, f"dest_lat_{route_num}").value()
            dest_lon = self.findChild(QDoubleSpinBox, f"dest_lon_{route_num}").value()

            if not route_name.strip():
                QMessageBox.warning(self, "Missing Name", f"Please enter a name for Route {route_num}")
                return

            # Create route ID
            route_id = f"primary_route_{route_num}"

            # Save to database
            self.db.add_probe_route(
                route_id=route_id,
                name=route_name,
                origin_lat=origin_lat,
                origin_lon=origin_lon,
                dest_lat=dest_lat,
                dest_lon=dest_lon,
                description=f"Primary route #{route_num} for congestion prediction",
                is_primary=True,
                priority=route_num
            )

            # Update status label
            status_label = self.findChild(QLabel, f"status_{route_num}")
            status_label.setText(f"✅ Saved to database")
            status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")

            QMessageBox.information(self, "Success", f"Route {route_num} saved successfully!")
            self.refresh_dashboard()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save route: {str(e)}")

    def collect_route_data(self, route_num):
        """Collect data for a specific route"""
        if not self.api_key:
            QMessageBox.warning(self, "API Key Required", "Please configure API key in the Dashboard tab first!")
            return

        try:
            route_id = f"primary_route_{route_num}"

            # Get route data from widgets
            origin_lat = self.findChild(QDoubleSpinBox, f"origin_lat_{route_num}").value()
            origin_lon = self.findChild(QDoubleSpinBox, f"origin_lon_{route_num}").value()
            dest_lat = self.findChild(QDoubleSpinBox, f"dest_lat_{route_num}").value()
            dest_lon = self.findChild(QDoubleSpinBox, f"dest_lon_{route_num}").value()

            # Collect data
            collector = TrafficDataCollector(self.api_key)
            result = collector.fetch_route_traffic(
                origin_lat=origin_lat,
                origin_lon=origin_lon,
                dest_lat=dest_lat,
                dest_lon=dest_lon,
                route_id=route_id
            )

            if result:
                status_label = self.findChild(QLabel, f"status_{route_num}")
                status_label.setText(f"✅ Data collected: {result['speed_kmh']} km/h")
                status_label.setStyleSheet("color: #4CAF50;")

                QMessageBox.information(
                    self, "Success",
                    f"Data collected for Route {route_num}:\n"
                    f"Travel time: {result['travel_time_seconds']}s\n"
                    f"Speed: {result['speed_kmh']} km/h"
                )
            else:
                QMessageBox.warning(self, "Failed", f"Could not collect data for Route {route_num}")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to collect data: {str(e)}")

    def view_route_on_map(self, route_num):
        """View route on map (opens Google Maps in browser)"""
        try:
            origin_lat = self.findChild(QDoubleSpinBox, f"origin_lat_{route_num}").value()
            origin_lon = self.findChild(QDoubleSpinBox, f"origin_lon_{route_num}").value()
            dest_lat = self.findChild(QDoubleSpinBox, f"dest_lat_{route_num}").value()
            dest_lon = self.findChild(QDoubleSpinBox, f"dest_lon_{route_num}").value()

            # Create Google Maps URL
            url = f"https://www.google.com/maps/dir/{origin_lat},{origin_lon}/{dest_lat},{dest_lon}"

            # Open in browser
            import webbrowser
            webbrowser.open(url)

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open map: {str(e)}")

    def load_primary_routes(self):
        """Load saved primary routes from database"""
        try:
            routes = self.db.get_primary_routes()

            if not routes:
                QMessageBox.information(self, "No Routes", "No saved primary routes found in database.")
                return

            # Load each route into its slot
            for route in routes:
                priority = route['priority']
                if 1 <= priority <= 5:
                    self.findChild(QLineEdit, f"route_name_{priority}").setText(route['name'])
                    self.findChild(QDoubleSpinBox, f"origin_lat_{priority}").setValue(route['origin_lat'])
                    self.findChild(QDoubleSpinBox, f"origin_lon_{priority}").setValue(route['origin_lon'])
                    self.findChild(QDoubleSpinBox, f"dest_lat_{priority}").setValue(route['dest_lat'])
                    self.findChild(QDoubleSpinBox, f"dest_lon_{priority}").setValue(route['dest_lon'])

                    # Update coords display
                    self.update_coords_display(priority)

                    status_label = self.findChild(QLabel, f"status_{priority}")
                    status_label.setText(f"✅ Loaded from database")
                    status_label.setStyleSheet("color: #4CAF50;")

            QMessageBox.information(self, "Success", f"Loaded {len(routes)} primary routes!")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load routes: {str(e)}")

    def collect_data_from_5_routes(self):
        """Collect data from all 5 primary routes"""
        if not self.api_key:
            QMessageBox.warning(self, "API Key Required", "Please configure API key in the Dashboard tab first!")
            return

        try:
            collector = TrafficDataCollector(self.api_key)
            success_count = 0

            for route_num in range(1, 6):
                route_id = f"primary_route_{route_num}"
                origin_lat = self.findChild(QDoubleSpinBox, f"origin_lat_{route_num}").value()
                origin_lon = self.findChild(QDoubleSpinBox, f"origin_lon_{route_num}").value()
                dest_lat = self.findChild(QDoubleSpinBox, f"dest_lat_{route_num}").value()
                dest_lon = self.findChild(QDoubleSpinBox, f"dest_lon_{route_num}").value()

                result = collector.fetch_route_traffic(
                    origin_lat=origin_lat,
                    origin_lon=origin_lon,
                    dest_lat=dest_lat,
                    dest_lon=dest_lon,
                    route_id=route_id
                )

                if result:
                    success_count += 1
                    status_label = self.findChild(QLabel, f"status_{route_num}")
                    status_label.setText(f"✅ {result['speed_kmh']} km/h")
                    status_label.setStyleSheet("color: #4CAF50;")

            QMessageBox.information(
                self, "Collection Complete",
                f"Successfully collected data from {success_count}/5 routes!"
            )
            self.refresh_dashboard()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to collect data: {str(e)}")

    def geocode_origin(self, route_num):
        """Geocode origin location name to coordinates"""
        location_input = self.findChild(QLineEdit, f"origin_location_{route_num}")
        location_name = location_input.text().strip()

        if not location_name:
            QMessageBox.warning(self, "Missing Location", "Please enter an origin location name!")
            return

        try:
            geolocator = Nominatim(user_agent="digital_twin_traffic_simulator")
            location = geolocator.geocode(location_name)

            if location:
                # Set coordinates
                self.findChild(QDoubleSpinBox, f"origin_lat_{route_num}").setValue(location.latitude)
                self.findChild(QDoubleSpinBox, f"origin_lon_{route_num}").setValue(location.longitude)

                # Update display
                self.update_coords_display(route_num)

                QMessageBox.information(
                    self, "Location Found",
                    f"Origin: {location.address}\n"
                    f"Coordinates: {location.latitude:.6f}, {location.longitude:.6f}"
                )
            else:
                QMessageBox.warning(self, "Not Found", f"Could not find location: {location_name}")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Geocoding failed: {str(e)}")

    def geocode_destination(self, route_num):
        """Geocode destination location name to coordinates"""
        location_input = self.findChild(QLineEdit, f"dest_location_{route_num}")
        location_name = location_input.text().strip()

        if not location_name:
            QMessageBox.warning(self, "Missing Location", "Please enter a destination location name!")
            return

        try:
            geolocator = Nominatim(user_agent="digital_twin_traffic_simulator")
            location = geolocator.geocode(location_name)

            if location:
                # Set coordinates
                self.findChild(QDoubleSpinBox, f"dest_lat_{route_num}").setValue(location.latitude)
                self.findChild(QDoubleSpinBox, f"dest_lon_{route_num}").setValue(location.longitude)

                # Update display
                self.update_coords_display(route_num)

                QMessageBox.information(
                    self, "Location Found",
                    f"Destination: {location.address}\n"
                    f"Coordinates: {location.latitude:.6f}, {location.longitude:.6f}"
                )
            else:
                QMessageBox.warning(self, "Not Found", f"Could not find location: {location_name}")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Geocoding failed: {str(e)}")

    def update_coords_display(self, route_num):
        """Update the coordinates display label"""
        origin_lat = self.findChild(QDoubleSpinBox, f"origin_lat_{route_num}").value()
        origin_lon = self.findChild(QDoubleSpinBox, f"origin_lon_{route_num}").value()
        dest_lat = self.findChild(QDoubleSpinBox, f"dest_lat_{route_num}").value()
        dest_lon = self.findChild(QDoubleSpinBox, f"dest_lon_{route_num}").value()

        coords_display = self.findChild(QLabel, f"coords_display_{route_num}")
        coords_display.setText(
            f"Origin: ({origin_lat:.4f}, {origin_lon:.4f}) → Dest: ({dest_lat:.4f}, {dest_lon:.4f})"
        )
        coords_display.setStyleSheet("font-size: 9pt; color: #2196F3;")

    def start_scheduled_collection(self):
        """Start scheduled data collection"""
        if not self.api_key:
            QMessageBox.warning(self, "API Key Required", "Please configure API key in the Dashboard tab first!")
            return

        interval = self.collection_interval_spin.value()
        duration = self.collection_duration_spin.value()

        reply = QMessageBox.question(
            self, "Start Scheduled Collection",
            f"Start collecting data every {interval} minutes for {duration} hours?\n\n"
            f"This will collect data from all 5 routes automatically.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            # Get route IDs
            route_ids = [f"primary_route_{i}" for i in range(1, 6)]

            # Start worker
            self.scheduled_worker = ScheduledCollectionWorker(
                self.api_key,
                route_ids,
                interval,
                duration
            )

            self.scheduled_worker.progress.connect(self.collection_status_label.setText)
            self.scheduled_worker.collection_complete.connect(self.on_scheduled_collection_update)
            self.scheduled_worker.finished.connect(self.on_scheduled_collection_finished)

            self.scheduled_worker.start()

            # Update UI
            self.start_scheduled_btn.setEnabled(False)
            self.stop_scheduled_btn.setEnabled(True)
            self.collection_status_label.setText("Status: 🟢 Running")
            self.collection_status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
            self.collection_progress_bar.setValue(0)

    def stop_scheduled_collection(self):
        """Stop scheduled data collection"""
        if self.scheduled_worker and self.scheduled_worker.isRunning():
            reply = QMessageBox.question(
                self, "Stop Collection",
                "Are you sure you want to stop the scheduled collection?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                self.scheduled_worker.stop()
                self.collection_status_label.setText("Status: ⏹️ Stopping...")

    def on_scheduled_collection_update(self, current, total):
        """Update progress bar during scheduled collection"""
        progress = int((current / total) * 100)
        self.collection_progress_bar.setValue(progress)

    def on_scheduled_collection_finished(self):
        """Handle scheduled collection completion"""
        self.start_scheduled_btn.setEnabled(True)
        self.stop_scheduled_btn.setEnabled(False)
        self.collection_status_label.setText("Status: ✅ Completed")
        self.collection_status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        self.collection_progress_bar.setValue(100)
        self.refresh_dashboard()

        QMessageBox.information(self, "Complete", "Scheduled data collection completed!")

    # ============== AREA TRAINING EVENT HANDLERS ==============

    def update_grid_info(self):
        """Update grid size info label"""
        n = self.grid_size_spin.value()
        points = n * n
        routes = 2 * n * (n - 1)  # horizontal + vertical connections
        self.grid_size_label.setText(f"{n} ({points} points, {routes} routes)")

    def update_collections_info(self):
        """Update expected collections info with flexible units"""
        # Convert duration to minutes
        duration_value = self.training_duration_spin.value()
        duration_unit = self.training_duration_unit.currentText()

        if duration_unit == "Minutes":
            total_duration_minutes = duration_value
        elif duration_unit == "Hours":
            total_duration_minutes = duration_value * 60
        elif duration_unit == "Days":
            total_duration_minutes = duration_value * 24 * 60
        else:  # Weeks
            total_duration_minutes = duration_value * 7 * 24 * 60

        # Convert interval to minutes
        interval_value = self.training_interval_spin.value()
        interval_unit = self.training_interval_unit.currentText()

        if interval_unit == "Minutes":
            interval_minutes = interval_value
        else:  # Hours
            interval_minutes = interval_value * 60

        # Calculate collections
        if interval_minutes > 0:
            total_collections = total_duration_minutes // interval_minutes
        else:
            total_collections = 0

        # Calculate duration in days for display
        duration_days = total_duration_minutes / (24 * 60)

        self.collections_info_label.setText(
            f"Expected: {total_collections:,} collections over {duration_days:.2f} days "
            f"(~{total_collections/max(duration_days, 1):.0f} per day)"
        )

    def create_monitored_area(self):
        """Create a new monitored area from map selection"""
        if not self.area_selected_bbox:
            QMessageBox.warning(
                self, "No Area Selected",
                "Please select an area on the map above!\n"
                "Use the rectangle tool to draw an area."
            )
            return

        area_name = self.area_name_input.text().strip()
        if not area_name:
            QMessageBox.warning(self, "Missing Name", "Please enter a name for the area!")
            return

        try:
            # Create area
            build_network = self.build_network_check.isChecked()
            grid_size = self.grid_size_spin.value()

            self.create_area_btn.setEnabled(False)
            self.create_area_btn.setText("Creating area...")

            result = self.area_manager.create_area_from_bbox(
                area_name=area_name,
                bbox=self.area_selected_bbox,
                build_network=build_network
            )

            self.current_area_id = result['area_id']

            # Calculate grid info for display
            grid_points = grid_size * grid_size
            grid_routes = 2 * grid_size * (grid_size - 1)

            # Update UI
            self.area_bbox_label.setText(
                f"Area created: {result['area_id']}\n"
                f"Network: {os.path.basename(result['network_file']) if result['network_file'] else 'Not built'}\n"
                f"Grid: {grid_size}x{grid_size} ({grid_points} points, {grid_routes} routes)"
            )
            self.area_bbox_label.setStyleSheet("color: #4CAF50; font-weight: bold;")

            self.training_area_info.setText(
                f"Area: {area_name} (ID: {result['area_id']})"
            )
            self.training_area_info.setStyleSheet("font-weight: bold; color: #4CAF50;")

            self.start_training_btn.setEnabled(True)

            QMessageBox.information(
                self, "Success",
                f"Monitored area created successfully!\n\n"
                f"Area ID: {result['area_id']}\n"
                f"Sampling Grid: {grid_size}x{grid_size}\n"
                f"Network: {'Built' if build_network else 'Skipped'}\n\n"
                f"You can now start training data collection."
            )

            self.refresh_area_stats()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to create area: {str(e)}")
            import traceback
            traceback.print_exc()
        finally:
            self.create_area_btn.setEnabled(True)
            self.create_area_btn.setText("Create Monitored Area")

    def load_existing_area(self):
        """Load an existing monitored area"""
        try:
            # Get all areas
            cursor = self.db.conn.cursor()
            cursor.execute("SELECT area_id, name, status FROM monitored_areas ORDER BY created_at DESC")
            areas = cursor.fetchall()

            if not areas:
                QMessageBox.information(self, "No Areas", "No monitored areas found in database.")
                return

            # Create selection dialog
            items = [f"{a['name']} (ID: {a['area_id']}, Status: {a['status']})" for a in areas]
            item, ok = QInputDialog.getItem(
                self, "Load Area", "Select an area:", items, 0, False
            )

            if ok and item:
                # Extract area_id from selection
                selected_index = items.index(item)
                area_id = areas[selected_index]['area_id']

                # Load area
                area = self.db.get_monitored_area(area_id)
                if area:
                    self.current_area_id = area_id
                    self.area_name_input.setText(area['name'])

                    self.area_bbox_label.setText(
                        f"Area loaded: {area['area_id']}\n"
                        f"Status: {area['status']}\n"
                        f"Collections: {area.get('collections_completed', 0)}/{area.get('collections_target', 0)}"
                    )
                    self.area_bbox_label.setStyleSheet("color: #4CAF50; font-weight: bold;")

                    self.training_area_info.setText(
                        f"Area: {area['name']} (ID: {area_id})"
                    )
                    self.training_area_info.setStyleSheet("font-weight: bold; color: #4CAF50;")

                    self.start_training_btn.setEnabled(area['status'] != 'completed')

                    self.refresh_area_stats()

                    QMessageBox.information(self, "Success", f"Area '{area['name']}' loaded successfully!")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load area: {str(e)}")

    def start_area_training(self):
        """Start area-wide training data collection"""
        if not self.current_area_id:
            QMessageBox.warning(self, "No Area", "Please create or load an area first!")
            return

        if not self.api_key:
            QMessageBox.warning(
                self, "API Key Required",
                "Please configure API key in the Digital Twin Dashboard tab first!"
            )
            return

        # Convert duration to minutes
        duration_value = self.training_duration_spin.value()
        duration_unit = self.training_duration_unit.currentText()

        if duration_unit == "Minutes":
            total_duration_minutes = duration_value
        elif duration_unit == "Hours":
            total_duration_minutes = duration_value * 60
        elif duration_unit == "Days":
            total_duration_minutes = duration_value * 24 * 60
        else:  # Weeks
            total_duration_minutes = duration_value * 7 * 24 * 60

        # Convert interval to minutes
        interval_value = self.training_interval_spin.value()
        interval_unit = self.training_interval_unit.currentText()

        if interval_unit == "Minutes":
            interval_minutes = interval_value
        else:  # Hours
            interval_minutes = interval_value * 60

        # Calculate days for display and storage
        duration_days = total_duration_minutes / (24 * 60)
        duration_weeks = duration_days / 7

        reply = QMessageBox.question(
            self, "Start Training",
            f"Start area-wide training data collection?\n\n"
            f"Duration: {duration_value} {duration_unit.lower()} ({duration_days:.2f} days)\n"
            f"Interval: Every {interval_value} {interval_unit.lower()}\n\n"
            f"This will run in the background and collect traffic data "
            f"across the entire area using the sampling grid.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            try:
                # Start training lifecycle in area manager
                self.area_manager.start_area_training(
                    area_id=self.current_area_id,
                    duration_weeks=duration_weeks,
                    interval_minutes=interval_minutes
                )

                # Start worker thread
                grid_size = self.grid_size_spin.value()
                self.area_training_worker = AreaTrainingWorker(
                    self.api_key,
                    self.current_area_id,
                    duration_days,
                    interval_minutes,
                    grid_size
                )

                self.area_training_worker.progress.connect(self.training_status_label.setText)
                self.area_training_worker.collection_update.connect(self.on_training_update)
                self.area_training_worker.finished.connect(self.on_training_finished)

                self.area_training_worker.start()

                # Update UI
                self.start_training_btn.setEnabled(False)
                self.stop_training_btn.setEnabled(True)
                self.training_status_label.setText("Status: Running")
                self.training_status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")

            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to start training: {str(e)}")

    def stop_area_training(self):
        """Stop area training"""
        if self.area_training_worker and self.area_training_worker.isRunning():
            reply = QMessageBox.question(
                self, "Stop Training",
                "Are you sure you want to stop training data collection?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                self.area_training_worker.stop()
                self.training_status_label.setText("Status: Stopping...")

    def on_training_update(self, current, total, snapshot):
        """Handle training progress update"""
        progress = int((current / total) * 100)
        self.training_progress_bar.setValue(progress)

        # Update snapshot info
        if snapshot:
            self.snapshot_info_label.setText(
                f"Latest snapshot: {snapshot.get('num_samples', 0)} samples, "
                f"Avg speed: {snapshot.get('avg_speed_kmh', 0):.1f} km/h"
            )

        self.refresh_area_stats()

    def on_training_finished(self):
        """Handle training completion"""
        self.start_training_btn.setEnabled(True)
        self.stop_training_btn.setEnabled(False)
        self.training_status_label.setText("Status: Completed")
        self.training_status_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        self.training_progress_bar.setValue(100)

        self.refresh_area_stats()

        QMessageBox.information(self, "Complete", "Training data collection completed!")

    def refresh_area_stats(self):
        """Refresh area statistics"""
        if not self.current_area_id:
            self.area_stats_table.setRowCount(0)
            return

        try:
            area = self.db.get_monitored_area(self.current_area_id)

            if area:
                stats_data = [
                    ("Area ID", area['area_id']),
                    ("Area Name", area['name']),
                    ("Status", area['status']),
                    ("Collections Completed", f"{area.get('collections_completed', 0)}/{area.get('collections_target', 0) or 'N/A'}"),
                    ("Training Duration", f"{area.get('training_duration_days', 0)} days" if area.get('training_duration_days') else "Not started"),
                    ("Training Started", area.get('training_start_date', 'N/A')[:19] if area.get('training_start_date') else "N/A"),
                    ("Network File", os.path.basename(area['sumo_network_file']) if area.get('sumo_network_file') else "Not built"),
                ]

                self.area_stats_table.setRowCount(len(stats_data))
                for i, (metric, value) in enumerate(stats_data):
                    self.area_stats_table.setItem(i, 0, QTableWidgetItem(metric))
                    self.area_stats_table.setItem(i, 1, QTableWidgetItem(str(value)))

        except Exception as e:
            print(f"Error refreshing area stats: {e}")

    def apply_styles(self):
        """Apply modern styling to the application"""
        self.setStyleSheet("""
            QWidget {
                background-color: #f5f5f5;
                color: #333;
            }

            QGroupBox {
                background-color: white;
                border: 2px solid #e0e0e0;
                border-radius: 10px;
                margin-top: 10px;
                padding-top: 15px;
                font-weight: bold;
            }

            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 5px;
                color: #2196F3;
            }

            QLineEdit {
                border: 2px solid #e0e0e0;
                border-radius: 8px;
                padding: 8px 12px;
                background-color: white;
                font-size: 10pt;
            }

            QLineEdit:focus {
                border: 2px solid #2196F3;
            }

            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 20px;
                font-weight: bold;
            }

            QPushButton:hover {
                background-color: #1976D2;
            }

            QPushButton:pressed {
                background-color: #0D47A1;
            }

            QPushButton:disabled {
                background-color: #cccccc;
                color: #666666;
            }

            QPushButton#run_btn {
                background-color: #4CAF50;
            }

            QPushButton#run_btn:hover {
                background-color: #45a049;
            }

            QSpinBox, QComboBox {
                border: 2px solid #e0e0e0;
                border-radius: 6px;
                padding: 5px;
                background-color: white;
            }

            QSpinBox:focus, QComboBox:focus {
                border: 2px solid #2196F3;
            }

            QTextEdit {
                border: 2px solid #e0e0e0;
                border-radius: 8px;
                background-color: #fafafa;
                padding: 10px;
            }

            QLabel {
                color: #333;
            }
            
            QTableWidget {
                border: 2px solid #e0e0e0;
                border-radius: 8px;
                background-color: white;
            }
            
            QTabWidget::pane {
                border: 2px solid #e0e0e0;
                border-radius: 8px;
                background-color: white;
            }
            
            QTabBar::tab {
                background-color: #e0e0e0;
                padding: 10px 20px;
                margin-right: 2px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
            }
            
            QTabBar::tab:selected {
                background-color: #2196F3;
                color: white;
            }
        """)

        self.run_btn.setObjectName("run_btn")

def run_app():
    """Launch the enhanced digital twin traffic simulator application"""
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI", 10))
    
    # Set application metadata
    app.setApplicationName("Digital Twin Traffic Simulator")
    app.setOrganizationName("Traffic Simulation Lab")
    
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    run_app()