import time
import os
import subprocess
import json
import platform
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
    """Konversi path relatif menjadi absolut."""
    if not os.path.isabs(path):
        return os.path.abspath(os.path.join(os.getcwd(), path))
    return path

# Fungsi untuk membaca konfigurasi dari file settings.json
def load_config():
    global config
    config_path = os.path.join(os.getcwd(), 'settings.json')  # Pastikan path universal
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        # Konversi path relatif menjadi absolut
        config["monitoring_folder"] = resolve_path(config["monitoring_folder"])
        config["data_file_path"] = resolve_path(config["data_file_path"])
        config["python_script_path"] = resolve_path(config["python_script_path"])
        console_logger.info("Konfigurasi berhasil dimuat.")
    except FileNotFoundError:
        error_logger.error(f"File konfigurasi {config_path} tidak ditemukan. Pastikan file tersedia.")
        exit(1)
    except json.JSONDecodeError:
        error_logger.error(f"Format file {config_path} tidak valid. Periksa isinya.")
        exit(1)

# Proses bot yang sedang berjalan
current_process = None

class FolderWatcher(FileSystemEventHandler):
    """Handler untuk memantau perubahan pada folder."""
    def on_modified(self, event):
        global current_process

        # Abaikan perubahan pada folder
        if event.is_directory:
            return

        # Cek perubahan pada file yang dipantau
        if os.path.abspath(event.src_path) == os.path.abspath(config["data_file_path"]):
            console_logger.info(f"Perubahan terdeteksi pada file: {event.src_path}")
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
    start_bot()

def start_bot():
    """Menjalankan skrip Python sebagai bot."""
    global current_process
    python_command = "python" if platform.system() == "Windows" else "python3"
    try:
        # Menjalankan main.py sebagai proses baru dengan input otomatis
        current_process = subprocess.Popen(
            [python_command, config["python_script_path"]],
            stdin=subprocess.PIPE,  # Mengatur stdin agar dapat mengirimkan input
            text=True  # Memastikan input dalam format teks (bukan byte)
        )

        # Jeda sebelum menjawab pertanyaan
        console_logger.info("Menunggu bot siap menerima input...")
        time.sleep(2)  # Jeda awal agar bot siap

        # Mengirimkan jawaban otomatis ke bot dengan jeda di antaranya
        for input_data in config["inputs"]:
            current_process.stdin.write(input_data)  # Kirim input ke proses
            current_process.stdin.flush()  # Pastikan data langsung dikirimkan
            console_logger.info(f"{input_data.strip()}")
            time.sleep(0.5)  # Jeda 0.5 detik di antara jawaban

        current_process.stdin.close()  # Tutup input setelah selesai menulis
        console_logger.info("Skrip bot berhasil dijalankan.")
    except FileNotFoundError:
        error_logger.error("Python3 tidak ditemukan. Pastikan Python3 sudah terinstal.")
    except Exception as e:
        error_logger.error(f"Terjadi kesalahan: {e}")

def start_monitoring():
    """Mulai memantau folder."""
    event_handler = FolderWatcher()
    observer = Observer()
    # Memantau folder berdasarkan konfigurasi
    observer.schedule(event_handler, path=config["monitoring_folder"], recursive=False)
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
