import time
import os
import subprocess
import json
import platform
import requests
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import logging
import threading

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

# Timer global untuk menunda tindakan
restart_timer = None
debounce_interval = 15  # Durasi tunggu (detik)

def resolve_path(path):
    """Konversi path relatif menjadi absolut berdasarkan lokasi skrip yang sedang dijalankan."""
    if not os.path.isabs(path):
        return os.path.abspath(os.path.join(os.path.dirname(__file__), path))
    return path

def load_config():
    global config
    config_path = 'settings.json'  # Menggunakan path relatif ke lokasi skrip utama
    try:
        # Membuka file dengan encoding UTF-8
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        # Konversi path relatif menjadi absolut untuk semua file yang diawasi
        config["files_to_watch"] = [resolve_path(file) for file in config["files_to_watch"]]
        config["python_script_path"] = resolve_path(config["python_script_path"])
        config["node_script_path"] = resolve_path(config["node_script_path"])
        console_logger.info("Konfigurasi berhasil dimuat.")
    except FileNotFoundError:
        error_logger.error(f"File konfigurasi {config_path} tidak ditemukan. Pastikan file tersedia.")
        exit(1)
    except json.JSONDecodeError:
        error_logger.error(f"Format file {config_path} tidak valid. Periksa isinya.")
        exit(1)
    except UnicodeDecodeError:
        error_logger.error(f"Terjadi masalah saat membaca file konfigurasi. Pastikan file {config_path} menggunakan encoding UTF-8.")
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
        'text': message,
        'parse_mode': 'HTML'  # Pastikan Telegram memproses emotikon dan karakter khusus dengan benar
    }
    
    try:
        response = requests.post(telegram_url, data=payload)
        if response.ok:
            console_logger.info(f"Notifikasi dikirim ke Telegram: {message}")
        else:
            error_logger.error(f"Gagal mengirim notifikasi ke Telegram: {response.status_code} - {response.text}")
    except requests.exceptions.RequestException as e:
        error_logger.error(f"Error saat mengirim notifikasi ke Telegram: {e}")

# Proses bot yang sedang berjalan
current_process = None

def restart_bot_with_debounce():
    """Memulai ulang bot dengan logika debounce (menunggu perubahan tidak ada selama interval tertentu)."""
    global restart_timer

    # Batalkan timer sebelumnya jika ada
    if restart_timer:
        restart_timer.cancel()

    # Mulai timer baru untuk restart bot
    restart_timer = threading.Timer(debounce_interval, restart_bot)
    restart_timer.start()
    console_logger.info(f"Menunggu {debounce_interval} detik untuk memastikan tidak ada perubahan lagi...")

class FolderWatcher(FileSystemEventHandler):
    """Handler untuk memantau perubahan pada file tertentu yang didefinisikan dalam konfigurasi."""
    
    def on_modified(self, event):
        """Memantau perubahan pada file yang diawasi."""
        if event.is_directory:
            return
        
        # Cek apakah file yang diubah ada dalam daftar files_to_watch
        if event.src_path in config["files_to_watch"]:
            console_logger.info(f"Perubahan terdeteksi pada file yang diawasi: {event.src_path} ({event.event_type})")
            restart_bot_with_debounce()  # Gunakan debounce logic

    def on_created(self, event):
        """Memantau file baru yang ditambahkan di folder yang diawasi."""
        if event.is_directory:
            return
        
        # Cek apakah file yang baru dibuat ada dalam daftar files_to_watch
        if event.src_path in config["files_to_watch"]:
            console_logger.info(f"File baru terdeteksi: {event.src_path} ({event.event_type})")
            restart_bot_with_debounce()  # Gunakan debounce logic

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
    restart_message = config["notifications"].get("restart_message", "⏳🌾 Bot {bot_name} sedang dimulai ulang... 🔄")
    restart_message = restart_message.format(bot_name=config["bot_name"])
    send_telegram_notification(restart_message)
    console_logger.info("Memulai ulang bot...")
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
        start_message = config["notifications"].get("start_message", "⏳🌾 {bot_name} telah dimulai! 🚀")
        start_message = start_message.format(bot_name=config["bot_name"])
        send_telegram_notification(start_message)
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
        error_message = config["notifications"].get("error_message", "⏳🌾 Error terjadi pada bot {bot_name}: {error_message} ⚠️")
        error_message = error_message.format(bot_name=config["bot_name"], error_message=str(e))
        send_telegram_notification(error_message)

def start_monitoring():
    """Mulai memantau file tertentu dalam daftar files_to_watch."""
    event_handler = FolderWatcher()
    observer = Observer()
    # Memantau direktori dari setiap file dalam files_to_watch
    for file_to_watch in config["files_to_watch"]:
        directory_to_watch = os.path.dirname(file_to_watch)  # Dapatkan direktori dari path file
        observer.schedule(event_handler, path=directory_to_watch, recursive=False)
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
