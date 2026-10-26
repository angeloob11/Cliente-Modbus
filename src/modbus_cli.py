import socket
import struct


HOST = "127.0.0.1"
PORT = 5020
PROTOCOL_ID = 0
UNIT_ID = 0XFF

class ClienteModbusTCP(socket.socket):
    def __init__(self, HOST:str, PORT:int):
        super().__init__(socket.AF_INET, socket.SOCK_STREAM)
        self.HOST = HOST
        self.PORT = PORT
        self.TransactionID = 0
        self.conectar()

    def conectar(self)->None:
        self.connect((self.HOST, self.PORT))

    def ejecutar(self, mensaje:bytes)->bytes:
        MBAP = self.CabeceraMBAP(mensaje)
        datos = MBAP + mensaje 
        print(datos)
        self.sendall(datos)
        self.TransactionID += 1
        return self.recv(1024)

    def leer(self, function:int, start:int, cantidad:int)->bytes:
        return self.ejecutar(function.to_bytes(1, 'big')+start.to_bytes(2, 'big')+cantidad.to_bytes(2,'big'))


    def cerrar(self)->None:
        self.close()

    def CabeceraMBAP(self, msg:bytes)->bytes:
        return struct.pack('>h',self.TransactionID)+struct.pack('>h',PROTOCOL_ID)+struct.pack('>h',len(msg)+1)+struct.pack('>B',UNIT_ID)



def main():
    MyCliente = ClienteModbusTCP(HOST, PORT)
    print(MyCliente.leer(1,20,10))
    MyCliente.close()

if __name__ == "__main__":
    main()