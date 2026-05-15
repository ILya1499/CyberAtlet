# DataBase.py
import sqlite3
import os

# Имя базы данных
DB_PATH = "DataBaseAngles.db"
conn = None

# Создание базы данных при запуске
def init_database():
    global conn
    if os.path.exists(DB_PATH):
        print(f"Файл '{DB_PATH}' существует.")
        conn = sqlite3.connect(DB_PATH)
    else:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS motor_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp_ms INTEGER NOT NULL,
            angle_left REAL NOT NULL,
            angle_right REAL NOT NULL,
            battery_voltage REAL NOT NULL,
            recording BOOLEAN NOT NULL,
            inserted_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)
        conn.commit()
        print("DataBase created.")
    print("DataBase opened.")

# Вставка записи в БД
def insert_record(data: dict):
    global conn
    if conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO motor_data (timestamp_ms, angle_left, angle_right, battery_voltage, recording)
        VALUES (?, ?, ?, ?, ?)
        """, (
            data["timestamp"],
            data["angle_left"],
            data["angle_right"],
            data.get("battery_voltage", data.get("battery", 0.0)),
            data.get("recording", False)
        ))
        conn.commit()
        record_id = cursor.lastrowid
        # Получаем полную запись для отправки по WebSocket
        cursor.execute("SELECT * FROM motor_data WHERE id = ?", (record_id,))
        row = cursor.fetchone()
        return {
            "id": row[0],
            "timestamp_ms": row[1],
            "angle_left": row[2],
            "angle_right": row[3],
            "battery_voltage": row[4],
            "recording": bool(row[5]),
            "inserted_at": row[6]
        }
    else: raise Exception("Database not init")

# Получение последних N записей
def get_last_records(limit: int = 50):
    global conn
    if conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT id, timestamp_ms, angle_left, angle_right, battery_voltage, recording, inserted_at
        FROM motor_data
        ORDER BY id DESC
        LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        return [
            {
                "id": r[0],
                "timestamp_ms": r[1],
                "angle_left": r[2],
                "angle_right": r[3],
                "battery_voltage": r[4],
                "recording": bool(r[5]),
                "inserted_at": r[6]
            }
            for r in rows
        ][::-1]  # Обратно в хронологическом порядке
    else: raise Exception("Database not init")

def close_database():
    global conn
    if conn:
        conn.close()
        print("DataBase closed")
    else: print("DataBase not init")

#@app.on_event("startup")
#async def startup_event():
#    init_database()


#new_record = insert_record(data) 
