import socket
import struct
import io
import threading
import time
import json
from PIL import Image as PilImage

from kivymd.app import MDApp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image as KivyImage
from kivymd.uix.label import MDLabel
from kivymd.uix.tab import MDTabs, MDTabsBase
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
    """Classe pour un onglet individuel dans MDTabs."""
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
        server_x = int(touch_x * ratio_x)
        server_y = int((img_h - touch_y) * ratio_y)
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

class SystemInfoLayout(GridLayout):
    """Le widget affichant les informations système de manière organisée."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.cols = 2
        # Padding et spacing réduits pour un look plus compact
        self.padding = 20
        self.spacing = 10
        
        self.info_labels = {}
        info_keys = {'os': 'Système d\'exploitation', 'node': 'Nom de la machine', 'user': 'Utilisateur', 'ip': 'Adresse IP'}
        
        for key, name in info_keys.items():
            # Colonne de gauche (descriptions)
            self.add_widget(MDLabel(
                text=f"{name}:", 
                halign='right', 
                theme_text_color="Secondary",
                size_hint_x=0.4  # La colonne prend 40% de la largeur
            ))
            # Colonne de droite (valeurs)
            self.info_labels[key] = MDLabel(
                text="N/A", 
                halign='left', 
                bold=True,
                size_hint_x=0.6 # La colonne prend 60% de la largeur
            )
            self.add_widget(self.info_labels[key])

    def update_info(self, info_dict):
        for key, value in info_dict.items():
            if key in self.info_labels:
                self.info_labels[key].text = value

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

    def _on_key_down(self, k, keycode, text, modifiers):
        send_command(f"KEYPRESS;{keycode[1]}")
        return True

    def _on_key_up(self, k, keycode):
        send_command(f"KEYRELEASE;{keycode[1]}")
        return True

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
                    print(f"[*] Tentative de connexion...")
                    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    client_socket.settimeout(3)
                    client_socket.connect((host, port))
                    client_socket.settimeout(None)
                    is_connected = True
                    print(f"[*] Connecté !")
                except (ConnectionRefusedError, socket.timeout):
                    time.sleep(5)
                except Exception as e:
                    print(f"[!] Erreur de connexion : {e}")
                    time.sleep(5)

            data = b""
            header_size = struct.calcsize("!L") + 1
            while is_connected and is_running:
                try:
                    while len(data) < header_size:
                        packet = client_socket.recv(4096)
                        if not packet: raise ConnectionResetError()
                        data += packet
                    
                    msg_type = data[0:1]
                    msg_size = struct.unpack("!L", data[1:header_size])[0]
                    data = data[header_size:]

                    while len(data) < msg_size:
                        data += client_socket.recv(4096)
                    
                    payload = data[:msg_size]
                    data = data[msg_size:]

                    if msg_type == b'\x01': # Image
                        res_header_size = struct.calcsize("!HH")
                        width, height = struct.unpack("!HH", payload[:res_header_size])
                        self.desktop_layout.server_resolution = (width, height)
                        jpeg_data = payload[res_header_size:]
                        Clock.schedule_once(lambda dt, frame=jpeg_data: self.desktop_layout.update_image(frame))
                    
                    elif msg_type == b'\x02': # Info Système
                        info_dict = json.loads(payload.decode('utf-8'))
                        Clock.schedule_once(lambda dt, info=info_dict: self.info_layout.update_info(info))

                except (ConnectionResetError, BrokenPipeError):
                    print("[!] Connexion perdue.")
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
