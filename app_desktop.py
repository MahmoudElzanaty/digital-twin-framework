import sys, os, json
from PyQt6.QtWidgets import QApplication, QWidget, QVBoxLayout, QPushButton, \
    QLineEdit, QLabel, QTextEdit, QHBoxLayout, QSpinBox, QComboBox
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtCore import QUrl, pyqtSlot, QObject, pyqtSignal
import folium
from folium import plugins
from geopy.geocoders import Nominatim

# import your framework modules
from modules.network_builder import generate_network
from modules.demand_generator import generate_routes
from modules.simulator import create_config, run_simulation

class MapBridge(QObject):
    regionSelected = pyqtSignal(str)  # emits JSON coords

    @pyqtSlot(str)
    def receiveRegion(self, data):
        self.regionSelected.emit(data)

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Digital Twin Traffic Simulator")
        self.resize(1200, 800)

        # Layout
        layout = QVBoxLayout(self)

        # ---- Top controls ----
        top = QHBoxLayout()
        self.location_input = QLineEdit()
        self.location_input.setPlaceholderText("Enter location (e.g., Berlin, Germany)")
        self.search_btn = QPushButton("Search")
        top.addWidget(self.location_input)
        top.addWidget(self.search_btn)
        layout.addLayout(top)

        # ---- Map ----
        self.view = QWebEngineView()
        layout.addWidget(self.view, 1)

        # ---- Bottom controls ----
        bottom = QHBoxLayout()
        self.duration = QSpinBox(); self.duration.setRange(300, 7200); self.duration.setValue(1800)
        self.intensity = QComboBox(); self.intensity.addItems(["Low","Medium","High"])
        self.run_btn = QPushButton("Run Simulation")
        bottom.addWidget(QLabel("Duration (s):")); bottom.addWidget(self.duration)
        bottom.addWidget(QLabel("Traffic:")); bottom.addWidget(self.intensity)
        bottom.addStretch(); bottom.addWidget(self.run_btn)
        layout.addLayout(bottom)

        # ---- Console ----
        self.console = QTextEdit(); self.console.setReadOnly(True)
        layout.addWidget(self.console, 1)

        # Map init
        self.map_file = "map.html"
        self.init_map([30.0444, 31.2357], 12)

        # Bridge for JS->Python
        self.bridge = MapBridge()
        self.bridge.regionSelected.connect(self.on_region_selected)

        # Connect buttons
        self.search_btn.clicked.connect(self.on_search)
        self.run_btn.clicked.connect(self.on_run)

        self.selected_bbox = None

    def log(self, text):
        self.console.append(text)
        QApplication.processEvents()

    def init_map(self, center, zoom):
        m = folium.Map(location=center, zoom_start=zoom)
        plugins.Draw(export=True, draw_options={"polygon": False, "circle": False}).add_to(m)
        folium.LayerControl().add_to(m)
        m.save(self.map_file)
        self.view.setUrl(QUrl.fromLocalFile(os.path.abspath(self.map_file)))

    def on_search(self):
        loc = self.location_input.text().strip()
        if not loc:
            self.log("[ERROR] Enter a location first.")
            return
        geolocator = Nominatim(user_agent="traffic_gui")
        geo = geolocator.geocode(loc)
        if not geo:
            self.log("[ERROR] Location not found.")
            return
        self.log(f"[INFO] Centering map on {geo.address}")
        self.init_map([geo.latitude, geo.longitude], 14)

    def on_region_selected(self, data):
        try:
            coords = json.loads(data)
            self.selected_bbox = coords
            self.log(f"[INFO] Selected region: {coords}")
        except Exception as e:
            self.log(f"[ERROR] Invalid region data: {e}")

    def on_run(self):
        location = self.location_input.text() or "custom_area"
        duration = self.duration.value()
        self.log(f"[INFO] Running simulation for {location} ...")

        try:
            out_dir = os.path.join("data", "networks")
            os.makedirs(out_dir, exist_ok=True)
            net_path = generate_network(location, out_dir)
            route_path = generate_routes(net_path, os.path.join("data","routes"), sim_time=duration)
            cfg_path = create_config(net_path, route_path, os.path.join("data","configs","simulation.sumocfg"))
            run_simulation(cfg_path, gui=True)
            self.log("[SUCCESS] Simulation finished.")
        except Exception as e:
            self.log(f"[ERROR] {e}")

def run_app():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    run_app()
