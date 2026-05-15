from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from datetime import datetime
import os
import csv
import struct
import uuid
import json
import logging
from typing import Optional, Dict, Any, List
import DataBase
import asyncio

app = FastAPI()
########################### 
LOG_DIR = "logs"          #
current_log_file = None   #
###########################

# Настройка путей
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

DATA_DIR = "motor_data"
os.makedirs(DATA_DIR, exist_ok=True)

# Глобальные переменные для реального времени
current_left_angle = 0.0
current_right_angle = 0.0
is_recording = False
current_filename = ""

##################################
current_status = {               #
    "recording": False,          #
    "battery_voltage": 0.0,      #
    "angle_left": 0.0,           #
    "angle_right": 0.0,          #
    "last_update": None,         #
    "wifi_connected": False,     #
    "esp32_connected": False,    #
    "hip_left": 0.0,
    "hip_right": 0.0,
    "knee_left": 0.0,
    "knee_right": 0.0,
    "load_level": 0,             # ← режим нагрузки: 0–100%
    "assist_level": 0,           # ← режим усиления
    "battery_percent": 100,      # ← заряд батареи (0–100%)
    "powerSaving_mode": "off"
}                                #
current_status.update({
    "powerSaving_mode": "off"  # или "low", "medium", "high"
})
pending_command = None           # Очередь команд от веб-интерфейса
##################################

#@app.get("/", response_class=HTMLResponse)
#async def control_page(request: Request):
#    return templates.TemplateResponse("control.html", {
#        "request": request,
#        "is_recording": is_recording
#    })

#############################################################
@app.get("/", response_class=HTMLResponse)                  #
async def control_page(request: Request):                   #
    return templates.TemplateResponse("mainHead.html", {    #
        "request": request,                                 #
        "is_recording": is_recording
    })

@app.get("/control", response_class=HTMLResponse)
async def control_page(request: Request):                   
    return templates.TemplateResponse("control.html", {     
        "request": request,
        "is_recording": is_recording
    })

#############################################################
@app.post("/update_angles")
async def update_angles(left: float, right: float):
    global current_left_angle, current_right_angle
    current_left_angle = left
    current_right_angle = right

    if is_recording and current_filename:
        timestamp = int(datetime.now().timestamp() * 1000)  # мс
        with open(os.path.join(DATA_DIR, current_filename), 'a', newline='') as file:
            writer = csv.writer(file)
            writer.writerow([timestamp, left, right])

    return {"status": "success"}


@app.post("/toggle_recording")
async def toggle_recording():
    global is_recording, current_filename

    if not is_recording:
        current_filename = f"motor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        with open(os.path.join(DATA_DIR, current_filename), 'w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["timestamp", "left_angle", "right_angle"])
        is_recording = True
    else:
        is_recording = False

    return {"is_recording": is_recording}


@app.get("/history", response_class=HTMLResponse)
async def history_page(request: Request):
    files = []
    for filename in os.listdir(DATA_DIR):
        if filename.endswith((".csv", ".bin")):
            filepath = os.path.join(DATA_DIR, filename)
            stat = os.stat(filepath)
            files.append({
                "name": filename,
                "size": stat.st_size,
                "created": datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M")
            })

    # Сортируем по дате создания (новые сверху)
    files.sort(key=lambda x: x["created"], reverse=True)

    return templates.TemplateResponse("history.html", {
        "request": request,
        "files": files
    })

#################################################################################
class ConnectionManager:                                                        #
    def __init__(self):                                                         #
        self.active_connections: List[WebSocket] = []                           #
                                                                                #
    async def connect(self, websocket: WebSocket):                              #
        await websocket.accept()                                                #
        self.active_connections.append(websocket)                               #
                                                                                #
    def disconnect(self, websocket: WebSocket):                                 #
        if websocket in self.active_connections:                                #
            self.active_connections.remove(websocket)                           #
                                                                                #
    async def broadcast(self, message: str):                                    #
        disconnected = []
        for connection in self.active_connections:                              #
            try:
                await connection.send_text(message)
            except:
                disconnected.append(connection)
        for connection in disconnected:
            self.disconnect(connection)

manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    print(f"WebSocket client connected. Total clients: {len(manager.active_connections)}")
    try:
        status_message = {
            "type": "status",
            "data": current_status
        }
        await websocket.send_text(json.dumps(status_message))
        print("Sent initial status to WebSocket client")
        while True:
            data = await websocket.receive_text()
            print(f"Received WebSocket message: {data}")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        print(f"WebSocket client disconnected. Total clients: {len(manager.active_connections)}")
    except Exception as e:
        print(f"WebSocket error: {e}")
        manager.disconnect(websocket)

@app.post("/start_recording")
async def start_recording():
    global pending_command, current_status
    pending_command = "start" # Устанавливаем команду
    current_status["recording"] = True
    start_new_log()
    logging.info("Web interface: START recording command queued")
    status_message = {
        "type": "status",
        "data": current_status
    }
    await manager.broadcast(json.dumps(status_message))
    return JSONResponse({"status": "success", "message": "Recording started"})

def start_new_log():
    global current_log_file
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(LOG_DIR, f"esp32_data_{timestamp}.jsonl")
        current_log_file = open(filename, "a")
        logging.info(f"Started recording to {filename}")
        return True
    except Exception as e:
        logging.error(f"Error starting recording: {str(e)}")
        return False


def stop_current_log():
    global current_log_file
    if current_log_file:
        current_log_file.close()
        current_log_file = None
        logging.info("Recording stopped")
    return True


@app.post("/stop_recording")
async def stop_recording():
    global pending_command, current_status
    pending_command = "stop" # Устанавливаем команду
    current_status["recording"] = False
    stop_current_log()
    logging.info("Web interface: STOP recording command queued")
    status_message = {
        "type": "status",
        "data": current_status
    }
    await manager.broadcast(json.dumps(status_message))
    return JSONResponse({"status": "success", "message": "Recording stopped"})

@app.get("/current_status")
async def get_current_status():
    return JSONResponse(current_status)

# Статус машины
@app.get("/status", response_class=HTMLResponse)
async def status_page(request: Request):
    return templates.TemplateResponse("status.html", {"request": request})

def log_data(data: Dict[str, Any]):
    global current_log_file
    if not current_log_file:
        return False
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        log_entry = {
            "server_timestamp": timestamp,
            "data": data
        }
        current_log_file.write(json.dumps(log_entry) + "\n")
        current_log_file.flush()
        return True
    except Exception as e:
        logging.error(f"Error writing to log file: {str(e)}")
        return False


@app.post("/data") # Теперь используется для данных и статуса
async def receive_data_and_status_and_send_command(request: Request):
    """Принимает данные и статус от ESP32 и возвращает команду в ответ."""
    global pending_command, last_esp32_update, current_status
    try:
        data = await request.json()
        # Обновляем время последнего контакта с ESP32
        last_esp32_update = datetime.now()
        
        # Получаем напряжение от ESP32#################################################
        voltage = data.get("battery_voltage", 0.0)

        # 🔋 Преобразуем напряжение в проценты (пример для Li-ion: 3.0V–4.2V)
        # 4.2V = 100%, 3.0V = 0%
        percent = max(0, min(100, int((voltage - 3.0) / (4.2 - 3.0) * 100)))##########

        # Обновляем глобальный статус из полученных данных
        current_status.update({
            "battery_voltage": data.get("battery_voltage", 0.0),
            "battery_percent": percent,
            "angle_left": data.get("angle_left", 0.0),
            "angle_right": data.get("angle_right", 0.0),
            "recording": data.get("recording", False),
            "last_update": datetime.now().isoformat(),
            "wifi_connected": True,
            "esp32_connected": True # Считаем подключенным при получении данных/статуса
        })

        # Записываем данные только если запись активна
        if current_status["recording"]:
            #DataBase.insert_record(data)
            log_data(data)
        
        DataBase.insert_record(data)    
        
        
        # Подготовка ответа с командой
        response_data = {"status": "success"} # Всегда успешный статус
        # Проверяем наличие команды
        if pending_command:
            response_data["command"] = pending_command # Добавляем команду в ответ
            pending_command = None # Сбрасываем команду после отправки
            print(f"Sending command '{response_data['command']}' to ESP32 in data response")
        else:
            response_data["command"] = "" # Явно указываем отсутствие команды

        # Рассылаем обновление через WebSocket
        status_message = {
            "type": "status",
            "data": current_status
        }
        await manager.broadcast(json.dumps(status_message))

        # Возвращаем JSON с командой
        return JSONResponse(response_data)
    except Exception as e:
        print(f"Error processing data/status: {e}")
        # В случае ошибки всё равно пытаемся вернуть команду, если есть
        response_data = {"status": "error", "command": pending_command if pending_command else ""}
        if pending_command:
             pending_command = None # Сбрасываем команду даже при ошибке
             print(f"Sending command '{response_data['command']}' to ESP32 in data error response")
        return JSONResponse(response_data, status_code=500)

#########################ЭНЕРГОСБЕРЕЖЕНИЕ#############################
@app.get("/powerSaving", response_class=HTMLResponse)
async def powerSaving_page(request: Request):
    return templates.TemplateResponse("powerSaving.html", {
        "request": request,
        "current_mode": current_status["powerSaving_mode"]  # ← именно отсюда
    })  


@app.post("/api/power_saving")
async def set_power_saving_mode(request: Request):
    global current_status  # ← ЭТО КРИТИЧЕСКИ ВАЖНО!
    try:
        data = await request.json()
        mode = data.get("mode")
        if mode not in ["off", "low", "medium", "high"]:
            raise HTTPException(400, "Invalid mode")
        
        # Обновляем глобальный статус
        current_status["powerSaving_mode"] = mode
        
        # Рассылаем всем через WebSocket
        status_message = {"type": "status", "data": current_status}
        await manager.broadcast(json.dumps(status_message))
        
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(500, detail=str(e))
    
##########################РЕЖИМЫ###########################################
# GET /mode — отображает страницу режимов
@app.get("/mode", response_class=HTMLResponse)
async def mode_page(request: Request):
    return templates.TemplateResponse("mode.html", {"request": request})


# POST /api/mode — обрабатывает выбор режима
@app.post("/api/mode")
async def set_operation_mode(request: Request):
    try:
        data = await request.json()
        mode = data.get("mode")

        # Допустимые режимы
        if mode not in ["load", "assist", "charge"]:
            raise HTTPException(400, "Invalid mode. Use: load, assist, charge")

        # 🔌 Здесь будет логика в будущем (пока заглушка)
        logging.info(f"Режим работы установлен: {mode}")

        # Опционально: можно отправить команду на ESP32 через pending_command
        # pending_command = f"mode:{mode}"

        return JSONResponse({"status": "success", "mode": mode})

    except Exception as e:
        logging.error(f"Ошибка при установке режима: {e}")
        raise HTTPException(500, detail="Failed to set mode")


@app.post("/update_load")
async def update_load_level(request: Request):
    try:
        data = await request.json()
        level = int(data.get("level", 0))
        level = max(0, min(100, level))  # безопасность

        global current_status
        current_status["load_level"] = level
        current_status["last_update"] = datetime.now().isoformat()


        # Рассылаем обновление
        await manager.broadcast(json.dumps({"type": "status", "data": current_status}))
        return {"status": "success", "load_level": level}
    except Exception as e:
        raise HTTPException(500, detail=f"Ошибка: {e}")
    
@app.post("/update_assist")
async def update_assist_level(request: Request):
    try:
        data = await request.json()
        level = int(data.get("level", 0))
        level = max(0, min(100, level))  # 0–100

        global current_status
        current_status["assist_level"] = level
        current_status["last_update"] = datetime.now().isoformat()


        await manager.broadcast(json.dumps({"type": "status", "data": current_status}))
        return {"status": "success", "assist_level": level}
    except Exception as e:
        raise HTTPException(500, detail=f"Ошибка: {e}")
##################################################################################
#Статус сервера
@app.get("/api/server_status")
async def get_server_status():
    """Возвращает внутренний статус сервера (не зависит от ESP32)."""
    import os
    from datetime import datetime

    # Считаем файлы в DATA_DIR
    csv_files = [f for f in os.listdir(DATA_DIR) if f.endswith('.csv')]
    bin_files = [f for f in os.listdir(DATA_DIR) if f.endswith('.bin')]
    
    # Проверяем, открыта ли БД
    db_open = DataBase.conn is not None if hasattr(DataBase, 'conn') else False

    return {
        "server_uptime": datetime.now().isoformat(),
        "database_connected": db_open,
        "websocket_clients": len(manager.active_connections),
        "data_files": {
            "csv_count": len(csv_files),
            "bin_count": len(bin_files),
            "total_size_bytes": sum(
                os.path.getsize(os.path.join(DATA_DIR, f)) 
                for f in csv_files + bin_files
            )
        },
        "power_saving_mode": current_status["powerSaving_mode"],
        "is_recording_via_web": is_recording,  # запись, запущенная с веб-интерфейса
        "logs_dir_exists": os.path.exists(LOG_DIR),
        "motor_data_dir": DATA_DIR
    }


##################################################################################

@app.post("/upload_data_file")
async def upload_data_file(
        file: UploadFile = File(...),
        file_type: str = Form("bin")
):
    if file_type not in ["bin", "csv"]:
        raise HTTPException(400, detail="Invalid file type")

    try:
        # Создаём папку, если её нет
        os.makedirs(DATA_DIR, exist_ok=True)

        # Генерируем имя файла
        ext = file.filename.split('.')[-1] if '.' in file.filename else file_type
        filename = f"data_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.{ext}"
        filepath = os.path.join(DATA_DIR, filename)

        # Сохраняем файл
        content = await file.read()

        # Для .bin файлов проверяем размер
        if file_type == "bin" and len(content) % 12 != 0:
            raise HTTPException(400, detail="Invalid .bin file size (must be divisible by 12 bytes)")

        # Записываем файл
        with open(filepath, 'wb') as f:
            f.write(content)

        # Автоматическая конвертация для .bin
        if file_type == "bin":
            csv_filename = filename.replace('.bin', '.csv')
            csv_path = os.path.join(DATA_DIR, csv_filename)

            try:
                # Конвертируем
                with open(filepath, 'rb') as bin_file, open(csv_path, 'w', newline='', encoding='utf-8') as csv_file:
                    writer = csv.writer(csv_file)
                    writer.writerow(['timestamp', 'left_angle', 'right_angle'])

                    while True:
                        chunk = bin_file.read(12)
                        if not chunk:
                            break
                        if len(chunk) != 12:
                            continue

                        ms = struct.unpack('<l', chunk[0:4])[0]
                        left = struct.unpack('<f', chunk[4:8])[0]
                        right = struct.unpack('<f', chunk[8:12])[0]
                        writer.writerow([ms, left, right])

                print(f"Конвертация успешна: {filename} → {csv_filename}")  # Логируем
                return {"status": "success", "filename": csv_filename}

            except Exception as e:
                if os.path.exists(filepath):
                    os.remove(filepath)
                raise HTTPException(500, detail=f"Conversion failed: {str(e)}")

        return {"status": "success", "filename": filename}

    except Exception as e:
        raise HTTPException(500, detail=f"Upload failed: {str(e)}")


@app.get("/file_data/{filename}")
async def get_file_data(filename: str):
    filepath = os.path.join(DATA_DIR, filename)

    if not os.path.exists(filepath):
        raise HTTPException(404, detail="File not found")

    data = []
    with open(filepath, 'r') as file:
        reader = csv.reader(file)
        next(reader)  # Пропускаем заголовок

        for row in reader:
            if len(row) == 3:
                try:
                    data.append({
                        "timestamp": int(row[0]),
                        "left_angle": float(row[1]),
                        "right_angle": float(row[2])
                    })
                except ValueError:
                    continue

    return {"data": data}


@app.post("/convert_existing_bin/{filename}")
async def convert_existing_bin(filename: str):
    if not filename.endswith('.bin'):
        raise HTTPException(status_code=400, detail="Only .bin files are allowed")

    filepath = os.path.join(DATA_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="File not found")

    try:
        csv_filename = filename.replace('.bin', '.csv')
        csv_path = os.path.join(DATA_DIR, csv_filename)

        # Читаем бинарный файл правильно
        with open(filepath, 'rb') as binfile, open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
            csvwriter = csv.writer(csvfile)
            csvwriter.writerow(['timestamp', 'left_angle', 'right_angle'])

            while True:
                chunk = binfile.read(12)
                if not chunk:
                    break

                if len(chunk) != 12:
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid .bin file structure (incomplete record)"
                    )

                ms = struct.unpack('<l', chunk[0:4])[0]
                left = struct.unpack('<f', chunk[4:8])[0]
                right = struct.unpack('<f', chunk[8:12])[0]
                csvwriter.writerow([ms, left, right])

        # Возвращаем CSV файл
        return FileResponse(
            path=csv_path,
            filename=csv_filename,
            media_type='text/csv'
        )

    except struct.error as e:
        if 'csv_path' in locals() and os.path.exists(csv_path):
            os.remove(csv_path)
        raise HTTPException(
            status_code=400,
            detail=f"Binary file structure error: {str(e)}"
        )
    except Exception as e:
        if 'csv_path' in locals() and os.path.exists(csv_path):
            os.remove(csv_path)
        raise HTTPException(
            status_code=500,
            detail=f"Conversion error: {str(e)}"
        )


@app.post("/convert_bin_to_csv")
async def convert_bin_to_csv(bin_path: str, csv_path: str):
    """Конвертирует .bin в .csv"""
    time_ms = []
    left = []
    right = []

    with open(bin_path, 'rb') as datafile, open(csv_path, 'w', newline='') as csvfile:
        csvwriter = csv.writer(csvfile)

        data = datafile.read()
        count_bytes = len(data)
        count_strings = count_bytes // 12

        for i in range(count_strings):
            # Распаковываем данные как в conventer.py (little-endian)
            ms = struct.unpack('<l', data[i*12:i*12+4])[0]  # timestamp (4 bytes)
            left_angle = struct.unpack('<f', data[i*12+4:i*12+8])[0]  # left (4 bytes)
            right_angle = struct.unpack('<f', data[i*12+8:i*12+12])[0]  # right (4 bytes)

            # Записываем в CSV
            csvwriter.writerow([ms, left_angle, right_angle])

@app.get("/motor_data/{filename}")
async def download_file(filename: str):
    filepath = os.path.join(DATA_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(404, detail="File not found")
    return FileResponse(filepath)


@app.delete("/delete_file/{filename}")
async def delete_file(filename: str):
    filepath = os.path.join(DATA_DIR, filename)

    if not os.path.exists(filepath):
        raise HTTPException(404, detail="File not found")

    try:
        os.remove(filepath)
        # Если это .bin файл, удаляем соответствующий .csv (если существует)
        if filename.endswith('.bin'):
            csv_file = filename.replace('.bin', '.csv')
            csv_path = os.path.join(DATA_DIR, csv_file)
            if os.path.exists(csv_path):
                os.remove(csv_path)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(500, detail=f"Delete failed: {str(e)}")

#################################Логика энергосбережения################################################




########################################################################################################

#################################Логика режимов#########################################################

@app.post("/apply_joints")
async def apply_joints(
    hip_left: float = Form(...),
    hip_right: float = Form(...),
    knee_left: float = Form(...),
    knee_right: float = Form(...)
):
    global current_status, pending_command
    # Обновляем статус
    current_status.update({
        "hip_left": float(hip_left),
        "hip_right": float(hip_right),
        "knee_left": float(knee_left),
        "knee_right": float(knee_right),
        "last_update": datetime.now().isoformat()
    })

    #Отправляем команду на ESP32
    pending_command = f"joints:{hip_left},{hip_right},{knee_left},{knee_right}"

    # Рассылаем обновление
    await manager.broadcast(json.dumps({"type": "status", "data": current_status}))
    return {"status": "success"}

@app.post("/apply_load")
async def apply_load(request: Request):
    try:
        data = await request.json()
        level = int(data.get("level", 0))
        level = max(0, min(100, level))

        global current_status, pending_command
        current_status["load_level"] = level
        current_status["last_update"] = datetime.now().isoformat()

        # 🔥 Отправляем команду на ESP32
        pending_command = f"load:{level}"

        await manager.broadcast(json.dumps({"type": "status", "data": current_status}))
        return {"status": "success", "load_level": level}
    except Exception as e:
        raise HTTPException(500, detail=f"Ошибка: {e}")

@app.post("/apply_assist")
async def apply_assist(request: Request):
    try:
        data = await request.json()
        level = int(data.get("level", 0))
        level = max(0, min(100, level))

        global current_status, pending_command
        current_status["assist_level"] = level
        current_status["last_update"] = datetime.now().isoformat()

        # 🔥 Отправляем команду на ESP32
        pending_command = f"assist:{level}"

        await manager.broadcast(json.dumps({"type": "status", "data": current_status}))
        return {"status": "success", "assist_level": level}
    except Exception as e:
        raise HTTPException(500, detail=f"Ошибка: {e}")

########################################################################################################

#################################Симуляция заряда#########################################################
# Задача симуляции
#async def simulate_battery_drain():
#    global current_status
 #   while True:
  #      await asyncio.sleep(15)  # каждые 15 сек
   #     if current_status["battery_percent"] > 0:
    #        current_status["battery_percent"] -= 1
     #       # Рассылаем обновление
      #      await manager.broadcast(
       #         json.dumps({"type": "status", "data": current_status})
        #    )



########################################################################################################

if __name__ == "__main__":
    import uvicorn
    
    #import threading ######################## cимуляция

    #################################################################################
    #Сервер на сайт                                                                 #
    try:                                                                            #
        DataBase.init_database()
        # Запуск симуляции в фоне (для демо) asyncio.create_task(simulate_battery_drain())
        uvicorn.run(app, host="0.0.0.0", port=8000)                                                    
    except KeyboardInterrupt:
        print("\nServer stopped by user")
    except Exception as e:
        print(f"Server error: {e}")




    #################################################################################
