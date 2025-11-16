import socket
import mss
import struct
from PIL import Image
import io
import threading
import json
import platform
import os
import time
import psutil
import re
import cpuinfo
import ssl

from pynput.mouse import Button, Controller as MouseController
from pynput.keyboard import Key, Controller as KeyboardController

# --- Fonctions utilitaires ---

def bytes_to_gb(bytes_val):
    return round(bytes_val / (1024**3), 1)

def parse_cpu_name(raw_name):
    match = re.search(r'(i[3579])[- ]?(\d{1,2})\d{2,}', raw_name)
    if match:
        brand = match.group(1).upper()
        gen_str = match.group(2)
        if gen_str.endswith('1') and gen_str != '11': suffix = 'st'
        elif gen_str.endswith('2') and gen_str != '12': suffix = 'nd'
        elif gen_str.endswith('3') and gen_str != '13': suffix = 'rd'
        else: suffix = 'th'
        return f"Intel Core {brand} ({gen_str}{suffix} Gen)"
    
    clean_name = raw_name.replace("(R)", "").replace("(TM)", "").replace("CPU", "").strip()
    clean_name = re.sub(r'@ \d+\.\d+GHz', '', clean_name).strip()
    if 'Family' in clean_name and 'Model' in clean_name:
        if 'Intel' in clean_name: return 'Intel Processor'
        if 'AMD' in clean_name: return 'AMD Processor'
    return " ".join(clean_name.split())

def get_system_info():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.1)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
    except Exception:
        ip = 'N/A'
    
    cpu_freq_str = "N/A"
    try:
        freq = psutil.cpu_freq()
        cpu_freq_str = f"{freq.current / 1000:.2f} GHz (Max: {freq.max / 1000:.2f} GHz)"
    except Exception:
        pass

    try:
        cpu_brand_raw = cpuinfo.get_cpu_info()['brand_raw']
        cpu_name = parse_cpu_name(cpu_brand_raw)
    except Exception:
        cpu_name = parse_cpu_name(platform.processor())

    arch = platform.architecture()[0]
    arch_str = "x64" if '64' in arch else "x86"
    final_cpu_name = f"{cpu_name} ({arch_str})"

    return {
        'os': f"{platform.system()} {platform.release()}",
        'node': platform.node(),
        'user': os.getlogin(),
        'ip': ip,
        'cpu_info': final_cpu_name,
        'cpu_freq': cpu_freq_str,
        'ram_total': f"{bytes_to_gb(psutil.virtual_memory().total)} Go",
        'disk_total_static': f"{bytes_to_gb(psutil.disk_usage('/').total)} Go"
    }

def get_realtime_stats():
    disk = psutil.disk_usage('/')
    return {
        'cpu_percent': psutil.cpu_percent(interval=None),
        'ram_percent': psutil.virtual_memory().percent,
        'disk_percent': disk.percent,
        'disk_used': disk.used,
        'disk_total': disk.total
    }

def send_message(sock, lock, msg_type, payload):
    message = msg_type + struct.pack("!L", len(payload)) + payload
    with lock:
        sock.sendall(message)

# --- Fonctions de thread (inchangées) ---

def send_screen(client_socket, lock, stop_event):
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        while not stop_event.is_set():
            try:
                sct_img = sct.grab(monitor)
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                mem_file = io.BytesIO()
                img.save(mem_file, 'JPEG', quality=75)
                jpeg_bytes = mem_file.getvalue()
                image_payload = struct.pack("!HH", monitor['width'], monitor['height']) + jpeg_bytes
                send_message(client_socket, lock, b'\x01', image_payload)
            except (ConnectionResetError, BrokenPipeError): stop_event.set(); break
            except Exception: stop_event.set(); break

def send_stats(client_socket, lock, stop_event):
    psutil.cpu_percent(interval=None)
    while not stop_event.is_set():
        try:
            stats = get_realtime_stats()
            stats_payload = json.dumps(stats).encode('utf-8')
            send_message(client_socket, lock, b'\x03', stats_payload)
            time.sleep(1)
        except (ConnectionResetError, BrokenPipeError): stop_event.set(); break
        except Exception: stop_event.set(); break

def get_pynput_key(key_name):
    try: return Key[key_name.lower()]
    except KeyError: return key_name

def receive_commands(client_socket, stop_event):
    mouse, keyboard = MouseController(), KeyboardController()
    data = b""
    payload_size = struct.calcsize("!L")
    while not stop_event.is_set():
        try:
            while len(data) < payload_size:
                packet = client_socket.recv(4096)
                if not packet: raise ConnectionResetError()
                data += packet
            packed_msg_size = data[:payload_size]
            data = data[payload_size:]
            msg_size = struct.unpack("!L", packed_msg_size)[0]
            while len(data) < msg_size: data += client_socket.recv(4096)
            cmd_data = data[:msg_size]
            data = data[msg_size:]
            command_str = cmd_data.decode('utf-8')
            parts = command_str.split(';')
            cmd_type = parts[0]
            if cmd_type == "CLICK":
                x, y, btn = int(parts[1]), int(parts[2]), parts[3]
                mouse.position = (x, y)
                mouse.click(Button.left if btn == "left" else Button.right, 1)
            elif cmd_type == "MOVE": mouse.position = (int(parts[1]), int(parts[2]))
            elif cmd_type == "KEYPRESS": keyboard.press(get_pynput_key(parts[1]))
            elif cmd_type == "KEYRELEASE": keyboard.release(get_pynput_key(parts[1]))
        except (ConnectionResetError, BrokenPipeError): stop_event.set(); break
        except Exception: pass

def handle_client(client_socket, addr):
    print(f"[*] Connexion sécurisée acceptée de {addr[0]}:{addr[1]}")
    stop_event = threading.Event()
    send_lock = threading.Lock()
    sys_info = get_system_info()
    info_payload = json.dumps(sys_info).encode('utf-8')
    send_message(client_socket, send_lock, b'\x02', info_payload)
    threads = [
        threading.Thread(target=send_screen, args=(client_socket, send_lock, stop_event)),
        threading.Thread(target=send_stats, args=(client_socket, send_lock, stop_event)),
        threading.Thread(target=receive_commands, args=(client_socket, stop_event))
    ]
    for t in threads:
        t.daemon = True
        t.start()
    for t in threads:
        t.join()
    print(f"[*] Connexion avec {addr[0]} terminée.")
    client_socket.close()

def start_server():
    host = '0.0.0.0'
    port = 1981  # CORRECTION: Port changé
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    context.load_cert_chain(certfile="cert.pem", keyfile="key.pem")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, port))
        sock.listen(5)
        print(f"[*] Le serveur sécurisé écoute sur {host}:{port}")
        
        with context.wrap_socket(sock, server_side=True) as ssock:
            while True:
                try:
                    client_socket, addr = ssock.accept()
                    threading.Thread(target=handle_client, args=(client_socket, addr), daemon=True).start()
                except KeyboardInterrupt:
                    print("\n[*] Arrêt du serveur.")
                    break
                except Exception as e:
                    print(f"[!] Erreur du serveur principal : {e}")
                    break

if __name__ == "__main__":
    start_server()
