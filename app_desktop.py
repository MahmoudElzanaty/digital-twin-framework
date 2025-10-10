import sys, os, json
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QPushButton,
    QLineEdit, QLabel, QTextEdit, QHBoxLayout, QSpinBox, QComboBox,
    QGroupBox, QFrame, QSplitter)
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtCore import QUrl, pyqtSlot, QObject, pyqtSignal, Qt
from PyQt6.QtGui import QFont, QPalette, QColor
import folium
from folium import plugins
from geopy.geocoders import Nominatim

# import your framework modules
from modules.network_builder import generate_network_from_bbox
from modules.demand_generator import generate_routes
from modules.simulator import create_config, run_simulation

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
        self.setWindowTitle("🚦 Digital Twin Traffic Simulator")
        self.resize(1400, 900)
        self.setup_ui()
        self.apply_styles()

        # Map init
        self.map_file = "map.html"

        # Bridge for JS->Python (setup BEFORE creating any pages)
        self.bridge = MapBridge()
        self.channel = QWebChannel()
        self.channel.registerObject("bridge", self.bridge)

        # IMPORTANT: Set web channel before loading any content
        self.view.page().setWebChannel(self.channel)

        # Connect signal AFTER registering
        self.bridge.regionSelected.connect(self.on_region_selected)

        # Connect load finished signal
        self.view.loadFinished.connect(self.on_map_loaded)

        # Initialize map (this will load the HTML)
        self.init_map([30.0444, 31.2357], 12)

        print("[DEBUG] Bridge and channel initialized")

        # Connect buttons
        self.search_btn.clicked.connect(self.on_search)
        self.run_btn.clicked.connect(self.on_run)
        self.clear_btn.clicked.connect(self.on_clear_selection)

        self.selected_bbox = None
        self.current_location = None

    def setup_ui(self):
        """Setup the user interface"""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # ===== HEADER =====
        header = QLabel("🌍 Digital Twin Traffic Simulator")
        header.setFont(QFont("Segoe UI", 24, QFont.Weight.Bold))
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(header)

        subtitle = QLabel("Search for a location, select an area on the map, and run your simulation")
        subtitle.setFont(QFont("Segoe UI", 10))
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(subtitle)

        # ===== SEARCH SECTION =====
        search_group = QGroupBox("📍 Location Search")
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

        search_layout.addWidget(self.location_input, 1)
        search_layout.addWidget(self.search_btn)
        main_layout.addWidget(search_group)

        # ===== MAP SECTION =====
        map_group = QGroupBox("🗺️ Interactive Map - Draw a rectangle to select simulation area")
        map_group.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        map_layout = QVBoxLayout(map_group)

        # Map instructions
        instructions = QLabel("💡 Tip: Use the rectangle tool (□) on the left side of the map to select your desired area")
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
        selection_layout.addWidget(self.selection_label, 1)
        selection_layout.addWidget(self.clear_btn)
        map_layout.addLayout(selection_layout)

        main_layout.addWidget(map_group, 2)

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
        controls_layout.addWidget(self.run_btn)

        main_layout.addWidget(controls_group)

        # ===== CONSOLE OUTPUT =====
        console_group = QGroupBox("📋 Console Output")
        console_group.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        console_layout = QVBoxLayout(console_group)

        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setFont(QFont("Consolas", 9))
        self.console.setMinimumHeight(150)
        console_layout.addWidget(self.console)

        main_layout.addWidget(console_group, 1)

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
        """)

        self.run_btn.setObjectName("run_btn")

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
        # Place this AFTER all other map setup to ensure libraries are loaded
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

                    // Verify bridge has receiveRegion method
                    if (bridgeObj && typeof bridgeObj.receiveRegion === 'function') {
                        console.log('[SUCCESS] bridge.receiveRegion is available');
                    } else {
                        console.error('[ERROR] bridge.receiveRegion not found!');
                    }

                    // Once bridge is ready, attach map listener
                    attachMapListener();
                });
                return true;
            }

            // Attach listener to map
            function attachMapListener() {
                console.log('[INIT] Waiting for map object...');

                var attempts = 0;
                var maxAttempts = 100;

                var checkMap = setInterval(function() {
                    attempts++;

                    if (typeof map !== 'undefined' && map) {
                        clearInterval(checkMap);
                        console.log('[SUCCESS] Map object found!');

                        // Attach draw listener
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

                                // Send to Python
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

            // Start initialization when DOM is ready
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

        # Save and load the map
        map_path = os.path.abspath(self.map_file)
        m.save(map_path)

        print(f"[DEBUG] Map saved to: {map_path}")
        print(f"[DEBUG] File exists: {os.path.exists(map_path)}")

        # Use QUrl.fromLocalFile for proper file URL
        file_url = QUrl.fromLocalFile(map_path)
        print(f"[DEBUG] Loading URL: {file_url.toString()}")

        self.view.setUrl(file_url)

    def on_map_loaded(self, ok):
        """Called when map finishes loading"""
        if ok:
            self.log("Map loaded successfully", "SUCCESS")
            print("[DEBUG] Map loaded, injecting listener code...")

            # Inject code to setup the draw listener after page loads
            # This ensures everything is ready
            inject_code = """
            (function() {
                console.log('[INJECT] Running injected code...');

                // Find the map variable (folium uses random IDs like map_xxx)
                function findMapVariable() {
                    for (var key in window) {
                        if (key.startsWith('map_') && window[key] && typeof window[key].on === 'function') {
                            return window[key];
                        }
                    }
                    return null;
                }

                // Wait for map and QWebChannel
                var attempts = 0;
                var checkReady = setInterval(function() {
                    attempts++;
                    var mapObj = findMapVariable();

                    if (mapObj && typeof QWebChannel !== 'undefined' && typeof qt !== 'undefined') {
                        clearInterval(checkReady);
                        console.log('[INJECT] Map and QWebChannel ready! Attempts:', attempts);

                        // Setup bridge
                        new QWebChannel(qt.webChannelTransport, function(channel) {
                            var bridge = channel.objects.bridge;
                            console.log('[INJECT] Bridge obtained:', bridge);

                            // Setup draw listener
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

            # Calculate approximate area
            lat_diff = abs(coords['north'] - coords['south'])
            lon_diff = abs(coords['east'] - coords['west'])
            area_km2 = lat_diff * lon_diff * 111 * 111  # rough approximation

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

        # Refresh map to remove drawn rectangles
        if self.current_location:
            geolocator = Nominatim(user_agent="digital_twin_traffic_simulator")
            geo = geolocator.geocode(self.current_location)
            if geo:
                self.init_map([geo.latitude, geo.longitude], 13)
        else:
            self.init_map([30.0444, 31.2357], 12)

    def on_run(self):
        """Run the simulation"""
        print(f"[DEBUG] on_run called. self.selected_bbox = {self.selected_bbox}")

        if not self.selected_bbox:
            self.log("Please select an area on the map first by drawing a rectangle!", "WARNING")
            print("[DEBUG] No bbox selected, aborting simulation")
            return

        location = self.location_input.text() or "custom_area"
        duration = self.duration.value()
        intensity = self.intensity.currentText()

        self.log("=" * 60, "INFO")
        self.log(f"Starting simulation for: {location}", "INFO")
        self.log(f"Duration: {duration}s | Traffic: {intensity}", "INFO")
        self.log("=" * 60, "INFO")

        try:
            # Disable UI during simulation
            self.run_btn.setEnabled(False)
            self.run_btn.setText("⏳ Running...")

            # Create output directories
            out_dir = os.path.join("data", "networks")
            os.makedirs(out_dir, exist_ok=True)

            # Generate network from selected bounding box
            self.log("Downloading OpenStreetMap data for selected area...", "INFO")
            net_path = generate_network_from_bbox(
                self.selected_bbox,
                location,
                out_dir
            )
            self.log(f"Network generated: {os.path.basename(net_path)}", "SUCCESS")

            # Generate routes
            self.log("Generating traffic demand...", "INFO")
            route_path = generate_routes(
                net_path,
                os.path.join("data", "routes"),
                sim_time=duration
            )
            self.log(f"Routes generated: {os.path.basename(route_path)}", "SUCCESS")

            # Create configuration
            self.log("Creating simulation configuration...", "INFO")
            cfg_path = create_config(
                net_path,
                route_path,
                os.path.join("data", "configs", "simulation.sumocfg")
            )
            self.log(f"Config created: {os.path.basename(cfg_path)}", "SUCCESS")

            # Run simulation
            self.log("Launching SUMO simulation GUI...", "INFO")
            run_simulation(cfg_path, gui=True)

            self.log("=" * 60, "SUCCESS")
            self.log("✅ Simulation completed successfully!", "SUCCESS")
            self.log("=" * 60, "SUCCESS")

        except Exception as e:
            self.log("=" * 60, "ERROR")
            self.log(f"❌ Simulation failed: {str(e)}", "ERROR")
            self.log("=" * 60, "ERROR")

        finally:
            # Re-enable UI
            self.run_btn.setEnabled(True)
            self.run_btn.setText("▶️ Run Simulation")

def run_app():
    app = QApplication(sys.argv)

    # Set application-wide font
    app.setFont(QFont("Segoe UI", 10))

    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    run_app()
