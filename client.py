import socket
import struct
import io
import threading
import time
import json
from PIL import Image as PilImage
import ssl
import re

from kivymd.app import MDApp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.image import Image as KivyImage
from kivymd.uix.label import MDLabel, MDIcon
from kivymd.uix.tab import MDTabs, MDTabsBase
from kivymd.uix.progressbar import MDProgressBar
from kivymd.uix.card import MDCard
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.textfield import MDTextField
from kivymd.uix.button import MDRaisedButton
from kivy.uix.screenmanager import Screen, ScreenManager
from kivy.graphics.texture import Texture
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.utils import get_color_from_hex

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

def bytes_to_gb(bytes_val):
    return round(bytes_val / (1024**3), 1)

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
        self.adaptive_height = True
        self.spacing = 15
        self.padding = 10
        self.add_widget(MDLabel(text=text, size_hint_x=0.25))
        self.progress_bar = MDProgressBar(value=0, size_hint_x=0.6)
        self.add_widget(self.progress_bar)
        self.percentage_label = MDLabel(text="0%", size_hint_x=0.15, halign='right')
        self.add_widget(self.percentage_label)

class DiskPerfRow(MDBoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.adaptive_height = True
        self.spacing = 15
        self.padding = 10
        self.add_widget(MDLabel(text="Disque", size_hint_x=0.25))
        self.progress_bar = MDProgressBar(value=0, size_hint_x=0.4)
        self.add_widget(self.progress_bar)
        self.usage_label = MDLabel(text="0/0 Go (0%)", size_hint_x=0.35, halign='right')
        self.add_widget(self.usage_label)

class SystemInfoLayout(MDBoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = 'vertical'
        self.padding = 20
        self.spacing = 15
        cards_container = MDBoxLayout(orientation='vertical', adaptive_height=True, spacing=15)
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
            'disk_total_static': InfoRow(icon="harddisk", text="Disque Total")
        }
        for widget in self.hw_info_widgets.values():
            hw_card.add_widget(widget)
        cards_container.add_widget(hw_card)
        perf_card = MDCard(orientation='vertical', padding=[15, 25, 15, 20], spacing=25, size_hint_y=None, adaptive_height=True)
        perf_card.add_widget(MDLabel(text="Performances en Temps Réel", font_style="H6"))
        self.realtime_widgets = {
            'cpu_percent': PerfRow(text="CPU"),
            'ram_percent': PerfRow(text="RAM"),
            'disk_percent': DiskPerfRow()
        }
        for widget in self.realtime_widgets.values():
            perf_card.add_widget(widget)
        cards_container.add_widget(perf_card)
        self.add_widget(cards_container)
        self.add_widget(BoxLayout())

    def update_static_info(self, info_dict):
        for key, value in info_dict.items():
            if key in self.static_info_widgets: self.static_info_widgets[key].value_label.text = str(value)
            if key in self.hw_info_widgets: self.hw_info_widgets[key].value_label.text = str(value)
    
    def update_realtime_stats(self, stats_dict):
        for key, value in stats_dict.items():
            if key in self.realtime_widgets:
                widget = self.realtime_widgets[key]
                if key == 'disk_percent':
                    widget.progress_bar.value = value
                    widget.usage_label.text = f"{bytes_to_gb(stats_dict['disk_used'])}/{bytes_to_gb(stats_dict['disk_total'])} Go ({int(value)}%)"
                    if value > 90: widget.progress_bar.color = get_color_from_hex("#FF0000")
                    else: widget.progress_bar.color = MDApp.get_running_app().theme_cls.primary_color
                elif key in ['cpu_percent', 'ram_percent']:
                    widget.progress_bar.value = value
                    widget.percentage_label.text = f"{int(value)}%"

class LoginScreen(Screen):
    IPV4_REGEX = re.compile(r"^((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        layout = MDBoxLayout(orientation='vertical', adaptive_height=True, size_hint_x=0.8, pos_hint={'center_x': 0.5, 'center_y': 0.5}, spacing=20)
        
        self.ip_field = MDTextField(
            hint_text="Adresse IP du serveur",
            input_filter=lambda string, from_undo: string if string.isdigit() or string == "." else "",
            on_text_validate=self.login # NOUVEAU: Déclenche login sur Entrée
        )
        self.port_field = MDTextField(
            hint_text="Port (ex: 9999)",
            input_filter='int',
            on_text_validate=self.login # NOUVEAU: Déclenche login sur Entrée
        )
        self.connect_button = MDRaisedButton(text="Se Connecter", on_release=self.login)
        self.error_label = MDLabel(halign='center', theme_text_color="Error")
        
        layout.add_widget(self.ip_field)
        layout.add_widget(self.port_field)
        layout.add_widget(self.connect_button)
        layout.add_widget(self.error_label)
        self.add_widget(layout)

    def login(self, *args):
        ip = self.ip_field.text.strip()
        port_text = self.port_field.text.strip()
        
        if not ip or not port_text:
            self.error_label.text = "L'adresse IP et le port sont requis."
            return
        
        if not self.IPV4_REGEX.match(ip):
            self.error_label.text = "Format d'adresse IP invalide (ex: 192.168.1.1)."
            return

        port = int(port_text)
        self.error_label.text = "Connexion en cours..."
        self.connect_button.disabled = True
        MDApp.get_running_app().start_connection(ip, port)

class MainScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
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
        self.add_widget(root)

class RemoteViewerApp(MDApp):
    def build(self):
        self.title = "Hosanna Remote Viewer"
        self.theme_cls.theme_style = "Dark"
        self.theme_cls.primary_palette = "Blue"
        self.sm = ScreenManager()
        self.sm.add_widget(LoginScreen(name='login'))
        self.sm.add_widget(MainScreen(name='main'))
        return self.sm

    def start_connection(self, host, port):
        threading.Thread(target=self.connect_and_receive, args=(host, port), daemon=True).start()

    def activate_remote_keyboard(self):
        self._keyboard = Window.request_keyboard(self._keyboard_closed, self.root)
        self._keyboard.bind(on_key_down=self._on_key_down)
        self._keyboard.bind(on_key_up=self._on_key_up)

    def release_remote_keyboard(self):
        if hasattr(self, '_keyboard') and self._keyboard:
            self._keyboard.unbind(on_key_down=self._on_key_down)
            self._keyboard.unbind(on_key_up=self._on_key_up)
            self._keyboard.release()
            self._keyboard = None

    def _keyboard_closed(self):
        self.release_remote_keyboard()
    
    def _on_key_down(self, k, keycode, text, modifiers): send_command(f"KEYPRESS;{keycode[1]}"); return True
    def _on_key_up(self, k, keycode): send_command(f"KEYRELEASE;{keycode[1]}"); return True

    def on_stop(self):
        global is_running
        is_running = False

    def connect_and_receive(self, host, port):
        global client_socket
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        context.load_verify_locations("cert.pem")
        context.check_hostname = False
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            client_socket = context.wrap_socket(sock, server_hostname=host)
            client_socket.connect((host, port))
            print(f"[*] Connecté au serveur sécurisé !")
            Clock.schedule_once(lambda dt: self.activate_remote_keyboard())
            Clock.schedule_once(lambda dt: setattr(self.sm, 'current', 'main'))
        except Exception as e:
            print(f"[!] Échec de la connexion : {e}")
            login_screen = self.sm.get_screen('login')
            error_message = "La connexion a échoué.\nVérifiez l'adresse et le port."
            Clock.schedule_once(lambda dt: setattr(login_screen.error_label, 'text', error_message))
            Clock.schedule_once(lambda dt: setattr(login_screen.connect_button, 'disabled', False))
            return
        data = b""
        header_size = struct.calcsize("!L") + 1
        while is_running:
            try:
                while len(data) < header_size:
                    packet = client_socket.recv(4096)
                    if not packet: raise ConnectionResetError("Connexion perdue")
                    data += packet
                msg_type, msg_size = data[0:1], struct.unpack("!L", data[1:header_size])[0]
                data = data[header_size:]
                while len(data) < msg_size: data += client_socket.recv(4096)
                payload = data[:msg_size]
                data = data[msg_size:]
                main_screen = self.sm.get_screen('main')
                if msg_type == b'\x01':
                    res_header_size = struct.calcsize("!HH")
                    width, height = struct.unpack("!HH", payload[:res_header_size])
                    main_screen.desktop_layout.server_resolution = (width, height)
                    jpeg_data = payload[res_header_size:]
                    Clock.schedule_once(lambda dt, f=jpeg_data: main_screen.desktop_layout.update_image(f))
                elif msg_type == b'\x02':
                    info = json.loads(payload.decode('utf-8'))
                    Clock.schedule_once(lambda dt, i=info: main_screen.info_layout.update_static_info(i))
                elif msg_type == b'\x03':
                    stats = json.loads(payload.decode('utf-8'))
                    Clock.schedule_once(lambda dt, s=stats: main_screen.info_layout.update_realtime_stats(s))
            except (ConnectionResetError, BrokenPipeError, OSError) as e:
                print(f"[!] Connexion perdue: {e}")
                if client_socket: client_socket.close()
                login_screen = self.sm.get_screen('login')
                Clock.schedule_once(lambda dt: self.release_remote_keyboard())
                Clock.schedule_once(lambda dt: setattr(login_screen.error_label, 'text', "Connexion perdue avec le serveur."))
                Clock.schedule_once(lambda dt: setattr(login_screen.connect_button, 'disabled', False))
                Clock.schedule_once(lambda dt: setattr(self.sm, 'current', 'login'))
                break
        if client_socket: client_socket.close()

if __name__ == "__main__":
    RemoteViewerApp().run()
