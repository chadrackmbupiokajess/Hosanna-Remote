import socket
import struct
import io
import threading
import time
import json
from PIL import Image as PilImage

from kivymd.app import MDApp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import Image as KivyImage
from kivymd.uix.label import MDLabel, MDIcon
from kivymd.uix.tab import MDTabs, MDTabsBase
from kivymd.uix.progressbar import MDProgressBar
from kivymd.uix.card import MDCard
from kivymd.uix.boxlayout import MDBoxLayout
from kivy.graphics.texture import Texture
from kivy.clock import Clock
from kivy.core.window import Window

is_running = True
client_socket = None

def send_command(command):
    if client_socket and is_running:
        try:
            cmd_bytes = command.encode('utf-8')
            message = struct.pack("!L", len(cmd_bytes)) + cmd_bytes
            client_socket.sendall(message)
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass

class Tab(BoxLayout, MDTabsBase):
    pass

class DesktopViewerLayout(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.server_resolution = (1, 1)
        self.screen_image = KivyImage(allow_stretch=True, keep_ratio=True)
        self.add_widget(self.screen_image)
    def update_image(self, jpeg_data):
        try:
            buf = io.BytesIO(jpeg_data)
            img = PilImage.open(buf)
            texture = Texture.create(size=img.size)
            texture.blit_buffer(img.tobytes(), colorfmt='rgb', bufferfmt='ubyte')
            texture.flip_vertical()
            self.screen_image.texture = texture
        except Exception: pass
    def _get_scaled_coords(self, touch):
        img = self.screen_image
        touch_x, touch_y = touch.x - img.x, touch.y - img.y
        img_w, img_h = img.norm_image_size
        ratio_x = self.server_resolution[0] / img_w if img_w > 0 else 0
        ratio_y = self.server_resolution[1] / img_h if img_h > 0 else 0
        server_x, server_y = int(touch_x * ratio_x), int((img_h - touch_y) * ratio_y)
        return server_x, server_y
    def on_touch_down(self, touch):
        if self.screen_image.collide_point(*touch.pos):
            x, y = self._get_scaled_coords(touch)
            btn = "left" if touch.button == 'left' else "right"
            send_command(f"CLICK;{x};{y};{btn}")
            return True
        return super().on_touch_down(touch)
    def on_touch_move(self, touch):
        if self.screen_image.collide_point(*touch.pos):
            x, y = self._get_scaled_coords(touch)
            send_command(f"MOVE;{x};{y}")
            return True
        return super().on_touch_move(touch)

class InfoRow(MDBoxLayout):
    def __init__(self, icon, text, **kwargs):
        super().__init__(**kwargs)
        self.adaptive_height = True
        self.add_widget(MDIcon(icon=icon, size_hint_x=None, width=40))
        self.add_widget(MDLabel(text=text, theme_text_color="Secondary"))
        self.value_label = MDLabel(text="N/A", halign='right', bold=True)
        self.add_widget(self.value_label)

class PerfRow(MDBoxLayout):
    def __init__(self, text, **kwargs):
        super().__init__(**kwargs)
        self.adaptive_height = True;
        self.padding = 10
        self.spacing = 15
        self.add_widget(MDLabel(text=text, size_hint_x=None, width=80))
        self.progress_bar = MDProgressBar(value=0)
        self.add_widget(self.progress_bar)
        self.percentage_label = MDLabel(text="0%", size_hint_x=None, width=50, halign='right')
        self.add_widget(self.percentage_label)

class SystemInfoLayout(MDBoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.padding = 20
        self.spacing = 15
        
        cards_container = MDBoxLayout(orientation='vertical', adaptive_height=True, spacing=15)

        # CORRECTION: Padding ajusté pour [gauche, haut, droite, bas]
        info_card = MDCard(orientation='vertical', padding=[15, 25, 15, 20], spacing=25, size_hint_y=None, adaptive_height=True)
        info_card.add_widget(MDLabel(text="Informations Générales", font_style="H6"))
        self.static_info_widgets = {
            'os': InfoRow(icon="desktop-classic", text="Système"),
            'node': InfoRow(icon="dns", text="Nom de la machine"),
            'user': InfoRow(icon="account", text="Utilisateur"),
            'ip': InfoRow(icon="ip-network", text="Adresse IP")
        }
        for widget in self.static_info_widgets.values():
            info_card.add_widget(widget)
        cards_container.add_widget(info_card)

        hw_card = MDCard(orientation='vertical', padding=[15, 25, 15, 20], spacing=25, size_hint_y=None, adaptive_height=True)
        hw_card.add_widget(MDLabel(text="Spécifications Matérielles", font_style="H6"))
        self.hw_info_widgets = {
            'cpu_info': InfoRow(icon="cpu-64-bit", text="Processeur"),
            'cpu_freq': InfoRow(icon="speedometer", text="Fréquence"),
            'ram_total': InfoRow(icon="memory", text="RAM Totale"),
            'disk_total': InfoRow(icon="harddisk", text="Disque Total")
        }
        for widget in self.hw_info_widgets.values():
            hw_card.add_widget(widget)
        cards_container.add_widget(hw_card)

        perf_card = MDCard(orientation='vertical', padding=[15, 25, 15, 20], spacing=25, size_hint_y=None, adaptive_height=True)
        perf_card.add_widget(MDLabel(text="Performances en Temps Réel", font_style="H6"))
        self.realtime_widgets = {
            'cpu_percent': PerfRow(text="CPU"),
            'ram_percent': PerfRow(text="RAM"),
            'disk_percent': PerfRow(text="Disque")
        }
        for widget in self.realtime_widgets.values():
            perf_card.add_widget(widget)
        cards_container.add_widget(perf_card)
        
        self.add_widget(cards_container)
        self.add_widget(BoxLayout())

    def update_static_info(self, info_dict):
        for key, value in info_dict.items():
            if key in self.static_info_widgets:
                self.static_info_widgets[key].value_label.text = str(value)
            if key in self.hw_info_widgets:
                self.hw_info_widgets[key].value_label.text = str(value)
    
    def update_realtime_stats(self, stats_dict):
        for key, value in stats_dict.items():
            if key in self.realtime_widgets:
                self.realtime_widgets[key].progress_bar.value = value
                self.realtime_widgets[key].percentage_label.text = f"{int(value)}%"

class RemoteViewerApp(MDApp):
    def build(self):
        self.title = "Hosanna Remote Viewer"
        self.theme_cls.theme_style = "Dark"
        self.theme_cls.primary_palette = "Blue"
        root = BoxLayout(orientation='vertical')
        tabs = MDTabs()
        desktop_tab = Tab(title='Bureau à distance')
        self.desktop_layout = DesktopViewerLayout()
        desktop_tab.add_widget(self.desktop_layout)
        info_tab = Tab(title='Informations Système')
        self.info_layout = SystemInfoLayout()
        info_tab.add_widget(self.info_layout)
        tabs.add_widget(desktop_tab)
        tabs.add_widget(info_tab)
        root.add_widget(tabs)
        self._keyboard = Window.request_keyboard(lambda: None, self.root)
        self._keyboard.bind(on_key_down=self._on_key_down, on_key_up=self._on_key_up)
        return root

    def _on_key_down(self, k, keycode, text, modifiers): send_command(f"KEYPRESS;{keycode[1]}"); return True
    def _on_key_up(self, k, keycode): send_command(f"KEYRELEASE;{keycode[1]}"); return True

    def on_start(self):
        threading.Thread(target=self.connect_and_receive, args=('127.0.0.1', 9999), daemon=True).start()

    def on_stop(self):
        global is_running
        is_running = False

    def connect_and_receive(self, host, port):
        global client_socket
        while is_running:
            is_connected = False
            while not is_connected and is_running:
                try:
                    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    client_socket.settimeout(3)
                    client_socket.connect((host, port))
                    client_socket.settimeout(None)
                    is_connected = True
                except (ConnectionRefusedError, socket.timeout): time.sleep(5)
                except Exception: time.sleep(5)
            data = b""
            header_size = struct.calcsize("!L") + 1
            while is_connected and is_running:
                try:
                    while len(data) < header_size:
                        packet = client_socket.recv(4096)
                        if not packet: raise ConnectionResetError()
                        data += packet
                    msg_type, msg_size = data[0:1], struct.unpack("!L", data[1:header_size])[0]
                    data = data[header_size:]
                    while len(data) < msg_size: data += client_socket.recv(4096)
                    payload = data[:msg_size]
                    data = data[msg_size:]
                    if msg_type == b'\x01': # Image
                        res_header_size = struct.calcsize("!HH")
                        width, height = struct.unpack("!HH", payload[:res_header_size])
                        self.desktop_layout.server_resolution = (width, height)
                        jpeg_data = payload[res_header_size:]
                        Clock.schedule_once(lambda dt, f=jpeg_data: self.desktop_layout.update_image(f))
                    elif msg_type == b'\x02': # Info Statique
                        info = json.loads(payload.decode('utf-8'))
                        Clock.schedule_once(lambda dt, i=info: self.info_layout.update_static_info(i))
                    elif msg_type == b'\x03': # Stats Temps Réel
                        stats = json.loads(payload.decode('utf-8'))
                        Clock.schedule_once(lambda dt, s=stats: self.info_layout.update_realtime_stats(s))
                except (ConnectionResetError, BrokenPipeError):
                    is_connected = False
                    if client_socket: client_socket.close()
                    Clock.schedule_once(lambda dt: setattr(self.desktop_layout.screen_image, 'texture', None))
                    break
                except Exception:
                    is_connected = False
                    if client_socket: client_socket.close()
                    break
        if client_socket: client_socket.close()

if __name__ == "__main__":
    RemoteViewerApp().run()
