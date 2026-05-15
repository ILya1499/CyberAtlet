import os
import struct
import datetime
import matplotlib.pyplot as plt
import sys
import csv, re
import codecs


time_ms = []
left = []
left_speed = []

right = []
right_speed = []

print(sys.argv)

filename = sys.argv[1]
timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")  # Форматируем дату и время
csv_filename = os.path.splitext(filename)[0] + "_" + timestamp + ".csv"  # Создаем имя CSV файла с таймштампом
start_points_x = []
start_points_y = []

with open(filename, 'rb') as datafile, open(csv_filename, 'w', newline='') as csvfile:  # Открываем и файл CSV:
  csvwriter = csv.writer(csvfile)
  #csvwriter.writerow(['ms', 'left_angle', 'right_angle'])  # Записываем заголовки столбцов

  data = datafile.read()

  countBytes = len(data)
  countStrings = (int)(countBytes/12)

  print(countStrings)

  for i in range(countStrings):
    (ms,) = struct.unpack('l', data[(i*12):((i * 12)+4)])
    (left_angle,) = struct.unpack('f', data[(i*12+4):((i * 12)+8)])
    (right_angle,) = struct.unpack('f', data[(i*12+8):((i * 12)+12)])

    print(f"{i}: {ms}, {left_angle}, {right_angle}")

    csvwriter.writerow([ms, left_angle, right_angle])  # Записываем данные в CSV

print(f"Данные записаны в файл: {csv_filename}")