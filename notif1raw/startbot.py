import time
import os
import subprocess
import json
import platform
import requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import logging

# Konfigurasi Logging
log_file_path = os.path.join(os.getcwd(), "log.txt")

# Logging untuk error ke file log.txt
error_logger = logging.getLogger("error_logger")
error_logger.setLevel(logging.ERROR)
file_handler = logging.FileHandler(log_file_path, mode='a')  # Logging ke file log.txt
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
error_logger.addHandler(file_handler)

# Logging untuk informasi penting langsung ke terminal
console_logger = logging.getLogger("console_logger")
console_logger.setLevel(logging.INFO)
console_handler = logging.StreamHandler()  # Logging ke terminal
console_handler.setFormatter(logging.Formatter('%(message)s'))
console_logger.addHandler(console_handler)

# Global variables untuk konfigurasi
config = {}

def resolve_path(path):
    """Konversi path relatif menjadi absolut berdasarkan lokasi skrip yang sedang dijalankan."""
    if not os.path.isabs(path):
        return os.path.abspath(os.path.join(os.path.dirname(__file__), path))
    return path

def load_config():
    global config
    config_path = 'settings.json'  # Menggunakan path relatif ke lokasi skrip utama
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        # Konversi path relatif menjadi absolut
        config["monitoring_folder"] = resolve_path(config["monitoring_folder"])
        config["python_script_path"] = resolve_path(config["python_script_path"])
        config["node_script_path"] = resolve_path(config["node_script_path"])
        console_logger.info(f"Konfigurasi berhasil dimuat. Nama Bot: {config['bot_name']}")
    except FileNotFoundError:
        error_logger.error(f"File konfigurasi {config_path} tidak ditemukan. Pastikan file tersedia.")
        exit(1)
    except json.JSONDecodeError:
        error_logger.error(f"Format file {config_path} tidak valid. Periksa isinya.")
        exit(1)

def send_telegram_notification(message):
    """Mengirim notifikasi ke Telegram dengan pesan yang diberikan."""
    bot_token = config.get("telegram_bot_token")
    chat_id = config.get("telegram_chat_id")
    
    if not bot_token or not chat_id:
        error_logger.error("Telegram bot token atau chat ID belum diatur dalam konfigurasi.")
        return
    
    telegram_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': message
    }
    
    try:
        response = requests.post(telegram_url, data=payload)
        if response.status_code == 200:
            console_logger.info(f"Notifikasi dikirim ke Telegram: {message}")
        else:
            error_logger.error(f"Gagal mengirim notifikasi ke Telegram: {response.status_code}")
    except requests.exceptions.RequestException as e:
        error_logger.error(f"Error saat mengirim notifikasi ke Telegram: {e}")

# Proses bot yang sedang berjalan
current_process = None

class FolderWatcher(FileSystemEventHandler):
    """Handler untuk memantau perubahan pada seluruh isi folder."""
    def on_any_event(self, event):
        global current_process

        # Abaikan perubahan pada folder yang sama tanpa file baru
        if event.is_directory:
            return

        # Restart bot jika ada perubahan dalam folder yang diawasi
        console_logger.info(f"Perubahan terdeteksi pada: {event.src_path} ({event.event_type})")
        restart_bot()

def stop_bot():
    """Menghentikan proses bot jika masih aktif."""
    global current_process
    if current_process:
        if current_process.poll() is None:  # Proses masih berjalan
            console_logger.info("Menghentikan bot...")
            current_process.terminate()
            try:
                current_process.wait(timeout=10)  # Tunggu hingga proses selesai
                console_logger.info("Bot berhasil dihentikan.")
            except subprocess.TimeoutExpired:
                console_logger.warning("Proses tidak merespons. Memaksa penghentian...")
                current_process.kill()  # Paksa berhenti
                current_process.wait()
        else:
            console_logger.info("Proses bot sudah berhenti.")
    else:
        console_logger.info("Tidak ada proses bot yang berjalan.")

def restart_bot():
    """Menghentikan bot yang sedang berjalan dan memulai ulang setelah jeda."""
    console_logger.info(f"Menunggu {config['restart_delay']} detik sebelum memulai ulang bot...")
    time.sleep(config['restart_delay'])
    stop_bot()
    console_logger.info("Memulai ulang bot...")
    send_telegram_notification(f"Bot {config['bot_name']} sedang dimulai ulang...")
    start_bot()

def start_bot():
    """Menjalankan skrip bot dengan perintah yang sesuai (Python atau Node.js)."""
    global current_process
    script_type = config.get("script_type", "python")  # Dapatkan tipe skrip dari konfigurasi
    if script_type == "python":
        command = "python" if platform.system() == "Windows" else "python3"
        script_path = config["python_script_path"]
    elif script_type == "node":
        command = "node"  # Gunakan "node" untuk menjalankan skrip Node.js
        script_path = config["node_script_path"]
    else:
        error_logger.error(f"Tipe skrip {script_type} tidak valid. Hanya mendukung 'python' atau 'node'.")
        return
    
    try:
        # Menjalankan skrip dengan perintah yang sesuai (Python atau Node.js)
        current_process = subprocess.Popen(
            [command, script_path],
            stdin=subprocess.PIPE,  # Mengatur stdin agar dapat mengirimkan input
            text=True  # Memastikan input dalam format teks (bukan byte)
        )

        console_logger.info("Menunggu bot siap menerima input...")
        send_telegram_notification(f"Bot {config['bot_name']} telah dimulai.")
        time.sleep(2)  # Jeda awal agar bot siap

        # Kirim input jika use_inputs diaktifkan
        if config.get("use_inputs", True):  # Default adalah True jika tidak ada konfigurasi
            for input_data in config["inputs"]:
                current_process.stdin.write(input_data + "\n")  # Menambahkan '\n' untuk menekan Enter
                current_process.stdin.flush()  # Pastikan data langsung dikirimkan
                time.sleep(1)  # Jeda 1 detik di antara jawaban
            current_process.stdin.close()  # Tutup input setelah selesai menulis

    except FileNotFoundError:
        error_logger.error(f"{command} tidak ditemukan. Pastikan {command} sudah terinstal.")
    except Exception as e:
        error_logger.error(f"Terjadi kesalahan: {e}")

def start_monitoring():
    """Mulai memantau folder."""
    event_handler = FolderWatcher()
    observer = Observer()
    # Memantau seluruh folder berdasarkan konfigurasi
    observer.schedule(event_handler, path=config["monitoring_folder"], recursive=True)
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == '__main__':
    # Memuat konfigurasi
    load_config()

    # Menjalankan skrip bot pertama kali saat skrip dimulai
    start_bot()
    start_monitoring()
