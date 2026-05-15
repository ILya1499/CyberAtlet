"""
EXO32 EXZO-Suit — Backend Server
FastAPI application for exoskeleton control with single-page landing support
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import os
import csv
import struct
import uuid
import json
import logging
from typing import Optional, Dict, Any, List
import asyncio

# Импорт модуля базы данных
import DataBase

# ============================================================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("server.log", encoding="utf-8", mode="a"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("exzo-server")

# ============================================================================
# ИНИЦИАЛИЗАЦИЯ ПРИЛОЖЕНИЯ
# ============================================================================
app = FastAPI(
    title="EXO32 EXZO-Suit API",
    description="Backend для управления экзоскелетом и лендинга",
    version="1.2.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # В продакшене заменить на конкретные домены
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# ============================================================================
# НАСТРОЙКА ПУТЕЙ
# ============================================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
DATA_DIR = os.path.join(BASE_DIR, "motor_data")
LOG_DIR = os.path.join(BASE_DIR, "logs")
MODELS_DIR = os.path.join(STATIC_DIR, "models")

# Создаём необходимые директории
for directory in [STATIC_DIR, TEMPLATES_DIR, DATA_DIR, LOG_DIR, MODELS_DIR]:
    os.makedirs(directory, exist_ok=True)

# Подключаем статику и шаблоны
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# ============================================================================
# ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ СОСТОЯНИЯ
# ============================================================================
current_status: Dict[str, Any] = {
    "recording": False,
    "battery_voltage": 0.0,
    "battery_percent": 100,
    "angle_left": 0.0,
    "angle_right": 0.0,
    "last_update": None,
    "wifi_connected": False,
    "esp32_connected": False,
    "hip_left": 0.0,
    "hip_right": 0.0,
    "knee_left": 0.0,
    "knee_right": 0.0,
    "load_level": 0,
    "assist_level": 0,
    "powerSaving_mode": "off",
    "operation_mode": "load"
}

# Переменные для записи данных
is_recording: bool = False
current_filename: str = ""
current_log_file = None
pending_command: Optional[str] = None
last_esp32_update: Optional[datetime] = None

# ============================================================================
# WEBSOCKET MANAGER
# ============================================================================
class ConnectionManager:
    """Управление WebSocket-подключениями для реального времени"""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Clients: {len(self.active_connections)}")
    
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket disconnected. Clients: {len(self.active_connections)}")
    
    async def broadcast(self, message: str):
        """Отправка сообщения всем подключённым клиентам"""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.warning(f"Failed to send to WebSocket: {e}")
                disconnected.append(connection)
        for connection in disconnected:
            self.disconnect(connection)

manager = ConnectionManager()

# ============================================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================================
def start_new_log() -> bool:
    """Создаёт новый файл лога для записи данных"""
    global current_log_file
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(LOG_DIR, f"esp32_data_{timestamp}.jsonl")
        current_log_file = open(filename, "a", encoding="utf-8")
        logger.info(f"Started recording to {filename}")
        return True
    except Exception as e:
        logger.error(f"Error starting recording: {e}")
        return False

def stop_current_log() -> bool:
    """Закрывает текущий файл лога"""
    global current_log_file
    if current_log_file:
        try:
            current_log_file.close()
            current_log_file = None
            logger.info("Recording stopped")
            return True
        except Exception as e:
            logger.error(f"Error stopping recording: {e}")
            return False
    return True

def log_data(data: Dict[str, Any]) -> bool:
    """Записывает данные в текущий лог-файл"""
    global current_log_file
    if not current_log_file:
        return False
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        log_entry = {"server_timestamp": timestamp, "data": data}
        current_log_file.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        current_log_file.flush()
        return True
    except Exception as e:
        logger.error(f"Error writing to log: {e}")
        return False

def voltage_to_percent(voltage: float) -> int:
    """Конвертирует напряжение Li-ion (3.0V–4.2V) в проценты"""
    return max(0, min(100, int((voltage - 3.0) / (4.2 - 3.0) * 100)))

# ============================================================================
# 🎯 ОСНОВНОЙ МАРШРУТ — ТОЛЬКО LANDING PAGE
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def landing_page(request: Request):
    """Главная и единственная страница — лендинг Cyber-Atlet.html"""
    #return templates.TemplateResponse("Exzo-suit.html", {
    #return templates.TemplateResponse("Cyber-Atlet.html", {
     #   "request": request,
      #  "is_recording": is_recording,
       # "current_status": current_status
    #})
    return FileResponse("/root/KiberAtlet/templates/Cyber-Atlet.html")

# ============================================================================
# 📡 API ENDPOINTS — ДАННЫЕ И УПРАВЛЕНИЕ (без HTML-страниц)
# ============================================================================

@app.post("/update_angles")
async def update_angles(left: float, right: float):
    """Обновление углов моторов + запись в CSV если активно"""
    global current_status
    
    current_status["angle_left"] = left
    current_status["angle_right"] = right
    current_status["last_update"] = datetime.now().isoformat()
    
    if is_recording and current_filename:
        timestamp = int(datetime.now().timestamp() * 1000)
        filepath = os.path.join(DATA_DIR, current_filename)
        with open(filepath, 'a', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow([timestamp, left, right])
    
    await manager.broadcast(json.dumps({"type": "status", "data": current_status}))
    return {"status": "success", "angles": {"left": left, "right": right}}

@app.post("/toggle_recording")
async def toggle_recording():
    """Переключение записи данных"""
    global is_recording, current_filename
    
    if not is_recording:
        current_filename = f"motor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        filepath = os.path.join(DATA_DIR, current_filename)
        with open(filepath, 'w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(["timestamp", "left_angle", "right_angle"])
        is_recording = True
        logger.info(f"Recording started: {current_filename}")
    else:
        is_recording = False
        logger.info("Recording stopped")
    
    current_status["recording"] = is_recording
    await manager.broadcast(json.dumps({"type": "status", "data": current_status}))
    return {"is_recording": is_recording}

@app.post("/start_recording")
async def start_recording():
    """Запуск записи (с WebSocket-уведомлением)"""
    global pending_command, is_recording, current_filename
    
    pending_command = "start"
    is_recording = True
    current_status["recording"] = True
    
    current_filename = f"motor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    filepath = os.path.join(DATA_DIR, current_filename)
    with open(filepath, 'w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(["timestamp", "left_angle", "right_angle"])
    
    start_new_log()
    logger.info("START recording command queued")
    
    await manager.broadcast(json.dumps({"type": "status", "data": current_status}))
    return JSONResponse({"status": "success", "message": "Recording started", "filename": current_filename})

@app.post("/stop_recording")
async def stop_recording():
    """Остановка записи (с WebSocket-уведомлением)"""
    global pending_command, is_recording
    
    pending_command = "stop"
    is_recording = False
    current_status["recording"] = False
    
    stop_current_log()
    logger.info("STOP recording command queued")
    
    await manager.broadcast(json.dumps({"type": "status", "data": current_status}))
    return JSONResponse({"status": "success", "message": "Recording stopped"})

@app.get("/current_status")
async def get_current_status():
    """Получение текущего статуса системы"""
    return JSONResponse(current_status)

# ============================================================================
# 📡 WEBSOCKET ENDPOINT
# ============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket для real-time обновлений статуса"""
    await manager.connect(websocket)
    try:
        await websocket.send_text(json.dumps({"type": "status", "data": current_status}))
        
        while True:
            data = await websocket.receive_text()
            logger.debug(f"WebSocket received: {data}")
            
            try:
                message = json.loads(data)
                msg_type = message.get("type")
                
                if msg_type == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
                elif msg_type == "command" and "action" in message:
                    action = message["action"]
                    logger.info(f"Received command: {action}")
                    
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON from WebSocket: {data}")
                
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)

# ============================================================================
# 📡 ESP32 COMMUNICATION
# ============================================================================

@app.post("/data")
async def receive_data_from_esp32(request: Request):
    """
    Принимает данные и статус от ESP32, возвращает команду в ответ.
    Основной эндпоинт для связи с микроконтроллером.
    """
    global pending_command, last_esp32_update, current_status
    
    try:
        data = await request.json()
        last_esp32_update = datetime.now()
        
        voltage = data.get("battery_voltage", 0.0)
        current_status.update({
            "battery_voltage": voltage,
            "battery_percent": voltage_to_percent(voltage),
            "angle_left": data.get("angle_left", 0.0),
            "angle_right": data.get("angle_right", 0.0),
            "recording": data.get("recording", current_status["recording"]),
            "last_update": datetime.now().isoformat(),
            "wifi_connected": True,
            "esp32_connected": True
        })
        
        if current_status["recording"]:
            log_data(data)
        
        try:
            DataBase.insert_record(data)
        except Exception as db_error:
            logger.warning(f"Database error (non-critical): {db_error}")
        
        response_data = {"status": "success"}
        if pending_command:
            response_data["command"] = pending_command
            logger.info(f"Sending command to ESP32: {pending_command}")
            pending_command = None
        else:
            response_data["command"] = ""
        
        await manager.broadcast(json.dumps({"type": "status", "data": current_status}))
        
        return JSONResponse(response_data)
        
    except Exception as e:
        logger.error(f"Error processing ESP32  {e}")
        response_data = {"status": "error", "command": pending_command or ""}
        if pending_command:
            pending_command = None
        return JSONResponse(response_data, status_code=500)

# ============================================================================
# ⚡ ЭНЕРГОСБЕРЕЖЕНИЕ (API только)
# ============================================================================

@app.post("/api/power_saving")
async def set_power_saving_mode(request: Request):
    """Установка режима энергосбережения"""
    global current_status
    try:
        data = await request.json()
        mode = data.get("mode")
        
        if mode not in ["off", "low", "medium", "high"]:
            raise HTTPException(status_code=400, detail="Invalid mode. Use: off, low, medium, high")
        
        current_status["powerSaving_mode"] = mode
        current_status["last_update"] = datetime.now().isoformat()
        
        logger.info(f"Power saving mode set to: {mode}")
        
        await manager.broadcast(json.dumps({"type": "status", "data": current_status}))
        
        return {"status": "success", "mode": mode}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting power saving mode: {e}")
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")

# ============================================================================
# ⚙️ РЕЖИМЫ РАБОТЫ (API только)
# ============================================================================

@app.post("/api/mode")
async def set_operation_mode(request: Request):
    """Установка режима работы экзоскелета"""
    global current_status, pending_command
    try:
        data = await request.json()
        mode = data.get("mode")
        
        if mode not in ["load", "assist", "charge"]:
            raise HTTPException(status_code=400, detail="Invalid mode. Use: load, assist, charge")
        
        current_status["operation_mode"] = mode
        current_status["last_update"] = datetime.now().isoformat()
        
        logger.info(f"Operation mode set to: {mode}")
        
        pending_command = f"mode:{mode}"
        
        await manager.broadcast(json.dumps({"type": "status", "data": current_status}))
        return JSONResponse({"status": "success", "mode": mode})
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error setting operation mode: {e}")
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")

@app.post("/update_load")
@app.post("/apply_load")
async def update_load_level(request: Request):
    """Обновление уровня нагрузки (0–100%)"""
    global current_status, pending_command
    try:
        data = await request.json()
        level = int(data.get("level", 0))
        level = max(0, min(100, level))
        
        current_status["load_level"] = level
        current_status["last_update"] = datetime.now().isoformat()
        
        pending_command = f"load:{level}"
        
        await manager.broadcast(json.dumps({"type": "status", "data": current_status}))
        return {"status": "success", "load_level": level}
    except Exception as e:
        logger.error(f"Error updating load level: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка: {e}")

@app.post("/update_assist")
@app.post("/apply_assist")
async def update_assist_level(request: Request):
    """Обновление уровня усиления (0–100%)"""
    global current_status, pending_command
    try:
        data = await request.json()
        level = int(data.get("level", 0))
        level = max(0, min(100, level))
        
        current_status["assist_level"] = level
        current_status["last_update"] = datetime.now().isoformat()
        
        pending_command = f"assist:{level}"
        
        await manager.broadcast(json.dumps({"type": "status", "data": current_status}))
        return {"status": "success", "assist_level": level}
    except Exception as e:
        logger.error(f"Error updating assist level: {e}")
        raise HTTPException(status_code=500, detail=f"Ошибка: {e}")

@app.post("/apply_joints")
async def apply_joints(
    hip_left: float = Form(...),
    hip_right: float = Form(...),
    knee_left: float = Form(...),
    knee_right: float = Form(...)
):
    """Применение углов сочленений"""
    global current_status, pending_command
    
    current_status.update({
        "hip_left": float(hip_left),
        "hip_right": float(hip_right),
        "knee_left": float(knee_left),
        "knee_right": float(knee_right),
        "last_update": datetime.now().isoformat()
    })
    
    pending_command = f"joints:{hip_left},{hip_right},{knee_left},{knee_right}"
    
    await manager.broadcast(json.dumps({"type": "status", "data": current_status}))
    return {"status": "success"}

# ============================================================================
# 📁 РАБОТА С ФАЙЛАМИ (API)
# ============================================================================

@app.post("/upload_data_file")
async def upload_data_file(
    file: UploadFile = File(...),
    file_type: str = Form("bin")
):
    """Загрузка файла данных (.bin или .csv)"""
    if file_type not in ["bin", "csv"]:
        raise HTTPException(status_code=400, detail="Invalid file type. Use: bin or csv")
    
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        
        ext = file.filename.split('.')[-1] if '.' in file.filename else file_type
        filename = f"data_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.{ext}"
        filepath = os.path.join(DATA_DIR, filename)
        
        content = await file.read()
        
        if file_type == "bin" and len(content) % 12 != 0:
            raise HTTPException(status_code=400, detail="Invalid .bin file size (must be divisible by 12 bytes)")
        
        with open(filepath, 'wb') as f:
            f.write(content)
        
        if file_type == "bin":
            csv_filename = filename.replace('.bin', '.csv')
            csv_path = os.path.join(DATA_DIR, csv_filename)
            
            with open(filepath, 'rb') as bin_file, open(csv_path, 'w', newline='', encoding='utf-8') as csv_file:
                writer = csv.writer(csv_file)
                writer.writerow(['timestamp', 'left_angle', 'right_angle'])
                
                for i in range(0, len(content), 12):
                    chunk = content[i:i+12]
                    if len(chunk) != 12:
                        continue
                    ms = struct.unpack('<l', chunk[0:4])[0]
                    left = struct.unpack('<f', chunk[4:8])[0]
                    right = struct.unpack('<f', chunk[8:12])[0]
                    writer.writerow([ms, left, right])
            
            logger.info(f"Converted {filename} → {csv_filename}")
            return {"status": "success", "filename": csv_filename}
        
        return {"status": "success", "filename": filename}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload error: {e}")
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

@app.get("/file_data/{filename}")
async def get_file_data(filename: str):
    """Получение данных из CSV файла для отображения"""
    filepath = os.path.join(DATA_DIR, filename)
    
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found")
    
    data = []
    with open(filepath, 'r', encoding='utf-8') as file:
        reader = csv.reader(file)
        next(reader, None)
        
        for row in reader:
            if len(row) >= 3:
                try:
                    data.append({
                        "timestamp": int(row[0]),
                        "left_angle": float(row[1]),
                        "right_angle": float(row[2])
                    })
                except (ValueError, IndexError):
                    continue
    
    return {"filename": filename, "data": data}

@app.post("/convert_existing_bin/{filename}")
async def convert_existing_bin(filename: str):
    """Конвертация существующего .bin файла в .csv"""
    if not filename.endswith('.bin'):
        raise HTTPException(status_code=400, detail="Only .bin files are allowed")
    
    filepath = os.path.join(DATA_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found")
    
    try:
        csv_filename = filename.replace('.bin', '.csv')
        csv_path = os.path.join(DATA_DIR, csv_filename)
        
        with open(filepath, 'rb') as binfile, open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            csvwriter = csv.writer(csvfile)
            csvwriter.writerow(['timestamp', 'left_angle', 'right_angle'])
            
            while True:
                chunk = binfile.read(12)
                if not chunk:
                    break
                if len(chunk) != 12:
                    raise HTTPException(status_code=400, detail="Invalid .bin structure")
                
                ms = struct.unpack('<l', chunk[0:4])[0]
                left = struct.unpack('<f', chunk[4:8])[0]
                right = struct.unpack('<f', chunk[8:12])[0]
                csvwriter.writerow([ms, left, right])
        
        return FileResponse(path=csv_path, filename=csv_filename, media_type='text/csv')
        
    except Exception as e:
        logger.error(f"Conversion error: {e}")
        raise HTTPException(status_code=500, detail=f"Conversion failed: {str(e)}")

@app.get("/motor_data/{filename}")
async def download_file(filename: str):
    """Скачивание файла данных"""
    filepath = os.path.join(DATA_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found")
    
    media_type = "text/csv" if filename.endswith('.csv') else "application/octet-stream"
    return FileResponse(filepath, filename=filename, media_type=media_type)

@app.delete("/delete_file/{filename}")
async def delete_file(filename: str):
    """Удаление файла данных"""
    filepath = os.path.join(DATA_DIR, filename)
    
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found")
    
    try:
        os.remove(filepath)
        if filename.endswith('.bin'):
            csv_file = filename.replace('.bin', '.csv')
            csv_path = os.path.join(DATA_DIR, csv_file)
            if os.path.exists(csv_path):
                os.remove(csv_path)
        logger.info(f"Deleted file: {filename}")
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Delete error: {e}")
        raise HTTPException(status_code=500, detail=f"Delete failed: {str(e)}")

# ============================================================================
# 🎨 ЛЕНДИНГ: ДОПОЛНИТЕЛЬНЫЕ API ENDPOINTS
# ============================================================================

@app.post("/api/contact")
async def handle_contact_form(
    name: str = Form(...),
    email: str = Form(...),
    message: Optional[str] = Form(None)
):
    """Обработка заявки с контактной формы лендинга"""
    try:
        logger.info(f"📩 New contact: {name} ({email})")
        
        contacts_file = os.path.join(BASE_DIR, "contacts.csv")
        file_exists = os.path.exists(contacts_file)
        
        with open(contacts_file, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["timestamp", "name", "email", "message"])
            writer.writerow([
                datetime.now().isoformat(),
                name.strip(),
                email.strip(),
                (message or "").strip()
            ])
        
        return {"status": "success", "message": "Заявка принята. Мы свяжемся с вами!"}
        
    except Exception as e:
        logger.error(f"Contact form error: {e}")
        raise HTTPException(status_code=500, detail="Не удалось отправить заявку")

@app.post("/api/upload_3d_model")
async def upload_3d_model(file: UploadFile = File(...)):
    """Загрузка пользовательской 3D-модели (.glb/.gltf)"""
    if not file.filename.lower().endswith((".glb", ".gltf")):
        raise HTTPException(status_code=400, detail="Допустимы только .glb и .gltf файлы")
    
    MAX_SIZE = 50 * 1024 * 1024
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="Файл слишком большой (макс. 50 МБ)")
    
    try:
        os.makedirs(MODELS_DIR, exist_ok=True)
        
        ext = file.filename.split('.')[-1].lower()
        filename = f"custom_{uuid.uuid4().hex}.{ext}"
        filepath = os.path.join(MODELS_DIR, filename)
        
        with open(filepath, 'wb') as f:
            f.write(content)
        
        logger.info(f"Uploaded 3D model: {filename}")
        
        return {
            "status": "success",
            "filename": filename,
            "url": f"/static/models/{filename}",
            "size": len(content)
        }
        
    except Exception as e:
        logger.error(f"3D upload error: {e}")
        raise HTTPException(status_code=500, detail=f"Загрузка не удалась: {str(e)}")

@app.get("/api/3d_models")
async def list_3d_models():
    """Список доступных 3D-моделей"""
    os.makedirs(MODELS_DIR, exist_ok=True)
    
    models = []
    for f in os.listdir(MODELS_DIR):
        if f.lower().endswith((".glb", ".gltf")):
            filepath = os.path.join(MODELS_DIR, f)
            models.append({
                "name": f,
                "size": os.path.getsize(filepath),
                "url": f"/static/models/{f}",
                "type": "glb" if f.endswith('.glb') else "gltf"
            })
    
    return {"models": models}

@app.get("/api/server_status")
async def get_server_status():
    """Статус сервера для мониторинга"""
    csv_files = [f for f in os.listdir(DATA_DIR) if f.endswith('.csv')]
    bin_files = [f for f in os.listdir(DATA_DIR) if f.endswith('.bin')]
    
    db_connected = False
    try:
        db_connected = hasattr(DataBase, 'conn') and DataBase.conn is not None
    except:
        pass
    
    return {
        "server_time": datetime.now().isoformat(),
        "database_connected": db_connected,
        "websocket_clients": len(manager.active_connections),
        "esp32_connected": current_status.get("esp32_connected", False),
        "last_esp32_update": last_esp32_update.isoformat() if last_esp32_update else None,
        "data_files": {
            "csv_count": len(csv_files),
            "bin_count": len(bin_files),
            "total_size_bytes": sum(
                os.path.getsize(os.path.join(DATA_DIR, f))
                for f in csv_files + bin_files
            )
        },
        "current_status": {
            "recording": current_status["recording"],
            "powerSaving_mode": current_status["powerSaving_mode"],
            "operation_mode": current_status["operation_mode"],
            "battery_percent": current_status["battery_percent"]
        }
    }

# ============================================================================
# 🔧 HEALTH CHECK & FALLBACK
# ============================================================================

@app.get("/health")
async def health_check():
    """Простая проверка работоспособности API"""
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    """Обработчик 404 — редирект на главную"""
    if request.url.path.startswith("/api"):
        return JSONResponse({"error": "Not found"}, status_code=404)
    return RedirectResponse(url="/", status_code=302)

# ============================================================================
# 🚀 ЗАПУСК СЕРВЕРА
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    logger.info("🚀 Starting EXO32 EXZO-Suit Server...")
    logger.info(f"📁 Data directory: {DATA_DIR}")
    logger.info(f"📁 Models directory: {MODELS_DIR}")
    logger.info("📄 Using single template: Cyber-Atlet.html")
    
    try:
        DataBase.init_database()
        logger.info("✅ Database initialized")
        
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=8000,
            log_level="info",
            access_log=True
        )
        
    except KeyboardInterrupt:
        logger.info("🛑 Server stopped by user")
    except Exception as e:
        logger.error(f"❌ Server error: {e}")
        raise