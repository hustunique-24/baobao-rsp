import serial
import time
def anmo():
    ser = serial.Serial('/dev/ttyACM0',115200)
    ser.write("b")



def qinxie():
    ser = serial.Serial('/dev/ttyACM0',115200)
    ser.write("d")
    time.sleep(1)
    response = ser.readline()
    #print(response)
    dd=response.split(':')
    #print dd

def shujv():
    ser = serial.Serial('/dev/ttyACM5', 115200)
    data = ser.read(100)
    return data
