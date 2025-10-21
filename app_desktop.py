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
from modules.auto_route_generator import AutoRouteGenerator
from modules.network_builder import generate_network_from_bbox
from modules.demand_generator import generate_routes
from modules.simulator import create_config, run_simulation
from modules.database import get_db
from modules.data_collector import TrafficDataCollector, TrafficDataAnalyzer
from modules.area_comparison import AreaBasedComparison
from modules.ai_predictor import SimpleTrafficPredictor, AdaptivePredictor
from modules.calibrator import SUMOCalibrator
from modules.area_manager import AreaManager
from modules.area_wide_collector import AreaWideCollector


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

class CalibrationWorker(QThread):
    """Background thread for calibration"""
    progress = pyqtSignal(str)
    iteration_complete = pyqtSignal(int, float)
    finished = pyqtSignal(dict)
    
    def __init__(self, network_file, route_file, mode='quick'):
        super().__init__()
        self.network_file = network_file
        self.route_file = route_file
        self.mode = mode
        self.running = True
    
    def run(self):
        try:
            calibrator = SUMOCalibrator(self.network_file, self.route_file)
            self.progress.emit("Starting calibration...")
            
            if self.mode == 'quick':
                best_params = calibrator.quick_calibration(num_tests=5)
            else:
                best_params = calibrator.sequential_optimization()
            
            calibrator.save_best_parameters()
            self.progress.emit("Calibration complete!")
            
            result = {
                'best_params': best_params,
                'best_error': calibrator.best_error,
                'history': calibrator.calibration_history
            }
            self.finished.emit(result)
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
            run_simulation(self.cfg_file, gui=False, scenario_id=self.scenario_id)
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
            generator = AutoRouteGenerator()
            location = self.location_input.text() or "custom_area"
            
            routes = generator.auto_generate_for_area(
                self.selected_bbox,
                location,
                strategy_combo.currentText(),
                num_spin.value()
            )
            
            QMessageBox.information(self, "Success", 
                f"Created {len(routes)} routes!")

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
        self.duration.setRange(300, 7200)
        self.duration.setValue(1800)
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
        """Create calibration center tab"""
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
        
        # Calibration info
        info_label = QLabel(
            "Calibration tunes SUMO parameters to match real Cairo traffic patterns.\n"
            "This improves simulation accuracy from ~23% error to <15%."
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        # Current status
        status_group = QGroupBox("📊 Current Status")
        status_layout = QVBoxLayout(status_group)
        
        self.calib_status_label = QLabel("Status: Not calibrated (using defaults)")
        self.calib_error_label = QLabel("Baseline Error: 22.84%")
        status_layout.addWidget(self.calib_status_label)
        status_layout.addWidget(self.calib_error_label)
        
        layout.addWidget(status_group)
        
        # Calibration controls
        controls_group = QGroupBox("🔧 Calibration Controls")
        controls_layout = QVBoxLayout(controls_group)
        
        # Mode selection
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(QLabel("Calibration Mode:"))
        self.calib_mode_combo = QComboBox()
        self.calib_mode_combo.addItems(["Quick (5 tests, ~20 min)", "Full (optimize all, ~1-2 hours)"])
        mode_layout.addWidget(self.calib_mode_combo)
        mode_layout.addStretch()
        controls_layout.addLayout(mode_layout)
        
        # Action buttons
        btn_layout = QHBoxLayout()
        
        self.run_calib_btn = QPushButton("▶️ Run Calibration")
        self.run_calib_btn.clicked.connect(self.run_calibration)
        btn_layout.addWidget(self.run_calib_btn)
        
        self.stop_calib_btn = QPushButton("⏹️ Stop")
        self.stop_calib_btn.setEnabled(False)
        btn_layout.addWidget(self.stop_calib_btn)
        
        self.load_calib_btn = QPushButton("📂 Load Saved Parameters")
        self.load_calib_btn.clicked.connect(self.load_calibration)
        btn_layout.addWidget(self.load_calib_btn)
        
        btn_layout.addStretch()
        controls_layout.addLayout(btn_layout)
        
        # Progress
        self.calib_progress = QProgressBar()
        self.calib_progress_label = QLabel("Ready")
        controls_layout.addWidget(self.calib_progress)
        controls_layout.addWidget(self.calib_progress_label)
        
        layout.addWidget(controls_group)
        
        # Parameters table
        params_group = QGroupBox("📋 SUMO Parameters")
        params_layout = QVBoxLayout(params_group)
        
        self.params_table = QTableWidget()
        self.params_table.setColumnCount(3)
        self.params_table.setHorizontalHeaderLabels(["Parameter", "Default", "Calibrated"])
        self.params_table.horizontalHeader().setStretchLastSection(True)
        params_layout.addWidget(self.params_table)
        
        self.populate_params_table()
        
        layout.addWidget(params_group)
        
        # Results
        results_group = QGroupBox("📈 Calibration Results")
        results_layout = QVBoxLayout(results_group)
        
        self.calib_results = QTextEdit()
        self.calib_results.setReadOnly(True)
        self.calib_results.setMaximumHeight(150)
        results_layout.addWidget(self.calib_results)
        
        layout.addWidget(results_group)

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
        
        self.export_results_btn = QPushButton("💾 Export Results")
        self.export_results_btn.clicked.connect(self.export_results)
        btn_layout.addWidget(self.export_results_btn)
        
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

            # ============ AUTO-GENERATE ROUTES ============
            location_name = self.location_input.text().strip() or "custom_area"
            location_name = location_name.replace(",", "").replace(" ", "_").lower()
            
            self.log("", "INFO")
            self.log("🎯 Auto-generating probe routes for selected area...", "INFO")
            
            try:
                generator = AutoRouteGenerator()
                
                # Get smart recommendations based on area size
                strategy = generator.get_recommended_strategy(coords)
                num_routes = generator.get_recommended_num_routes(coords)
                
                self.log(f"📊 Area: {area_km2:.2f} km² → {strategy} strategy, {num_routes} routes", "INFO")
                
                # Generate routes
                routes = generator.auto_generate_for_area(
                    bbox=coords,
                    location_name=location_name,
                    strategy=strategy,
                    num_routes=num_routes
                )
                
                self.log(f"✅ Auto-created {len(routes)} probe routes!", "SUCCESS")
                self.log(f"   Routes cover your simulation area and will be tracked", "INFO")
                self.log("", "INFO")
                
                # Show sample routes
                for route in routes[:3]:
                    self.log(f"   • {route['name']}", "INFO")
                
                if len(routes) > 3:
                    self.log(f"   • ... and {len(routes)-3} more routes", "INFO")
                
                self.log("", "INFO")
                
            except Exception as e:
                self.log(f"⚠️ Could not auto-generate routes: {str(e)}", "WARNING")
                self.log("   Don't worry - area-based comparison will still work", "INFO")
                import traceback
                traceback.print_exc()
            # =============================================

            print(f"[DEBUG] self.selected_bbox is now: {self.selected_bbox}")

        except Exception as e:
            self.log(f"Error processing region: {str(e)}", "ERROR")
            print(f"[DEBUG] Exception in on_region_selected: {e}")
            import traceback
            traceback.print_exc()

    def on_clear_selection(self):
        """Clear the current selection"""
        self.selected_bbox = None
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

            self.log("Downloading OpenStreetMap data for selected area...", "INFO")
            net_path = generate_network_from_bbox(
                self.selected_bbox,
                location,
                out_dir
            )
            self.log(f"Network generated: {os.path.basename(net_path)}", "SUCCESS")

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
                os.path.join("data", "configs", "simulation.sumocfg")
            )
            self.log(f"Config created: {os.path.basename(cfg_path)}", "SUCCESS")

            scenario_id = f"{location.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

            self.log("=" * 60, "INFO")
            self.log("🔬 DIGITAL TWIN MODE ENABLED", "INFO")
            self.log("🎯 DYNAMIC CALIBRATION ENABLED", "INFO")
            self.log(f"Scenario ID: {scenario_id}", "INFO")
            self.log("Simulation will track routes and compare with real data", "INFO")
            self.log("Parameters will adapt in real-time to match real traffic", "INFO")
            self.log("=" * 60, "INFO")

            self.log("Launching SUMO simulation...", "INFO")
            run_simulation(
                cfg_path,
                gui=True,
                scenario_id=scenario_id,
                enable_digital_twin=True,
                enable_dynamic_calibration=True  # ENABLED: Real-time parameter adaptation
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

    def populate_params_table(self):
        """Populate calibration parameters table"""
        default_params = {
            'tau': 1.0,
            'accel': 2.6,
            'decel': 4.5,
            'sigma': 0.5,
            'speedFactor': 1.0,
            'lcStrategic': 1.0
        }
        
        self.params_table.setRowCount(len(default_params))
        
        for i, (param, default) in enumerate(default_params.items()):
            self.params_table.setItem(i, 0, QTableWidgetItem(param))
            self.params_table.setItem(i, 1, QTableWidgetItem(f"{default:.3f}"))
            self.params_table.setItem(i, 2, QTableWidgetItem("-"))

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

    def run_calibration(self):
        """Run calibration"""
        network_file, route_file = self.find_latest_files()
        
        if not network_file or not route_file:
            QMessageBox.warning(
                self, "Files Required",
                "Run a simulation first to generate network and routes!"
            )
            return
        
        mode = 'quick' if 'Quick' in self.calib_mode_combo.currentText() else 'full'
        
        reply = QMessageBox.question(
            self, "Confirm Calibration",
            f"Run {mode} calibration?\n"
            f"This will take {'~20 minutes' if mode == 'quick' else '1-2 hours'}.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.calib_progress_label.setText("Running calibration...")
            self.worker = CalibrationWorker(network_file, route_file, mode)
            self.worker.progress.connect(self.calib_progress_label.setText)
            self.worker.finished.connect(self.on_calibration_finished)
            self.worker.start()
            
            self.run_calib_btn.setEnabled(False)
            self.stop_calib_btn.setEnabled(True)

    def on_calibration_finished(self, result):
        """Handle calibration completion"""
        self.run_calib_btn.setEnabled(True)
        self.stop_calib_btn.setEnabled(False)
        
        if result and 'best_error' in result:
            self.calib_error_label.setText(f"Calibrated Error: {result['best_error']:.2f}%")
            self.calib_status_label.setText("Status: ✅ Calibrated")
            
            if 'best_params' in result:
                for i in range(self.params_table.rowCount()):
                    param = self.params_table.item(i, 0).text()
                    if param in result['best_params']:
                        value = result['best_params'][param]
                        self.params_table.setItem(i, 2, QTableWidgetItem(f"{value:.3f}"))
            
            QMessageBox.information(
                self, "Calibration Complete",
                f"Calibration completed!\n"
                f"Error improved to: {result['best_error']:.2f}%"
            )

    def load_calibration(self):
        """Load saved calibration parameters"""
        filename = "data/calibration/best_params.txt"
        if os.path.exists(filename):
            with open(filename, 'r') as f:
                content = f.read()
            self.calib_results.setText(content)
            QMessageBox.information(self, "Loaded", "Calibration parameters loaded!")
        else:
            QMessageBox.warning(self, "Not Found", "No saved calibration found!")

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
        """View scenario details"""
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
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not load scenario: {str(e)}")

    def export_results(self):
        """Export results to file"""
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export Results", "results.txt", "Text Files (*.txt);;All Files (*)"
        )
        
        if filename:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(self.comparison_text.toPlainText())
            QMessageBox.information(self, "Exported", f"Results exported to {filename}")

    def find_latest_files(self):
        """Find latest network and route files"""
        net_dir = "data/networks"
        route_dir = "data/routes"
        
        network_file = None
        route_file = None
        
        if os.path.exists(net_dir):
            files = [f for f in os.listdir(net_dir) if f.endswith('.net.xml')]
            if files:
                files.sort(key=lambda x: os.path.getmtime(os.path.join(net_dir, x)))
                network_file = os.path.join(net_dir, files[-1])
        
        if os.path.exists(route_dir):
            files = [f for f in os.listdir(route_dir) if f.endswith('.rou.xml')]
            if files:
                files.sort(key=lambda x: os.path.getmtime(os.path.join(route_dir, x)))
                route_file = os.path.join(route_dir, files[-1])
        
        return network_file, route_file

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