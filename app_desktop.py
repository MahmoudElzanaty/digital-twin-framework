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
from modules.demand_generator import generate_routes
from modules.simulator import create_config, run_simulation
from modules.database import get_db
from modules.data_collector import TrafficDataCollector, TrafficDataAnalyzer
from modules.area_comparison import AreaBasedComparison
from modules.ai_predictor import SimpleTrafficPredictor, AdaptivePredictor
from modules.calibrator import SUMOCalibrator


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
        
        # Map and simulation state (ORIGINAL)
        self.map_file = "map.html"
        self.selected_bbox = None
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
        
        # Tab 2: Digital Twin Dashboard (NEW)
        self.tab_dashboard = self.create_dashboard_tab()
        self.tabs.addTab(self.tab_dashboard, "📊 Digital Twin Dashboard")
        
        # Tab 3: Calibration Center (NEW)
        self.tab_calibration = self.create_calibration_tab()
        self.tabs.addTab(self.tab_calibration, "🔧 Calibration Center")
        
        # Tab 4: AI Prediction (NEW)
        self.tab_ai = self.create_ai_tab()
        self.tabs.addTab(self.tab_ai, "🤖 AI Prediction")
        
        # Tab 5: Results & Analysis (NEW)
        self.tab_results = self.create_results_tab()
        self.tabs.addTab(self.tab_results, "📈 Results & Analysis")
        
        main_layout.addWidget(self.tabs)
        
        # Status bar
        self.status_label = QLabel("Ready")
        self.status_label.setFont(QFont("Segoe UI", 9))
        main_layout.addWidget(self.status_label)

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

        # Selection status
        selection_layout = QHBoxLayout()
        self.selection_label = QLabel("📌 No area selected")
        self.selection_label.setFont(QFont("Segoe UI", 10))
        self.clear_btn = QPushButton("🗑️ Clear Selection")
        self.clear_btn.setEnabled(False)
        self.clear_btn.setMinimumHeight(35)
        self.clear_btn.clicked.connect(self.on_clear_selection)
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

    # ============== TAB 2: DIGITAL TWIN DASHBOARD ==============
    
    def create_dashboard_tab(self):
        """Create digital twin dashboard"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
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
        
        return tab

    # ============== TAB 3: CALIBRATION CENTER ==============
    
    def create_calibration_tab(self):
        """Create calibration center tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
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
        
        return tab

    # ============== TAB 4: AI PREDICTION ==============
    
    def create_ai_tab(self):
        """Create AI prediction tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
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
        
        return tab

    # ============== TAB 5: RESULTS & ANALYSIS ==============
    
    def create_results_tab(self):
        """Create results and analysis tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
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
        """Handle region selection from map"""
        print(f"[DEBUG] on_region_selected called with data: {data}")
        try:
            coords = json.loads(data)
            self.selected_bbox = coords
            print(f"[DEBUG] Parsed coordinates: {coords}")

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
            self.log(f"Scenario ID: {scenario_id}", "INFO")
            self.log("Simulation will track routes and compare with real data", "INFO")
            self.log("=" * 60, "INFO")

            self.log("Launching SUMO simulation...", "INFO")
            run_simulation(
                cfg_path,
                gui=True,
                scenario_id=scenario_id,
                enable_digital_twin=True
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