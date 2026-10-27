import socket
import struct


HOST = "127.0.0.1"
PORT = 502
PROTOCOL_ID = 0
UNIT_ID = 0XFF

class RespuestaModbus(bytes):
    def __new__(cls, datos: bytes, cantidad: int):
        obj = super().__new__(cls, datos)
        obj.cantidad = cantidad
        return obj


class RespuestaBits(RespuestaModbus):
    def to_binary(self) -> list[int]:
        return [(self[i // 8] >> (i % 8)) & 1
                for i in range(self.cantidad)]


class RespuestaRegistros(RespuestaModbus):
    def to_int(self) -> list[int]:
        return list(struct.unpack(f">{self.cantidad}H", self))

    def to_signed(self) -> list[int]:
        return list(struct.unpack(f">{self.cantidad}h", self))



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
        #print(datos)
        self.sendall(datos)
        self.TransactionID += 1
        MBAP_recibido = struct.unpack('>HHHB', self.recv(7))
        pdu = self.recv(MBAP_recibido[2]-1)
        return pdu

    def leer(self, function:int, start:int, cantidad:int)->bytes:
        return self.ejecutar(function.to_bytes(1, 'big')+start.to_bytes(2, 'big')+cantidad.to_bytes(2,'big'))


    def cerrar(self)->None:
        self.close()

    def CabeceraMBAP(self, msg:bytes)->bytes:
        return struct.pack('>H',self.TransactionID)+struct.pack('>H',PROTOCOL_ID)+struct.pack('>H',len(msg)+1)+struct.pack('>B',UNIT_ID)

    #FUNCION 1
    def LeerCoils(self, inicio:int, numero_coils:int)->bytes:
        pdu = self.leer(1, inicio, numero_coils)
        return RespuestaBits(pdu[2:], numero_coils)

    #FUNCION 2
    def LeerDiscreteInputs(self, inicio:int, numero_coils:int)->bytes:
        pdu = self.leer(2, inicio, numero_coils)
        return RespuestaBits(pdu[2:], numero_coils)

    #FUNCION 3
    def ReadHoldingRegisters(self, inicio: int, numero_registros: int) -> RespuestaRegistros:
        pdu = self.leer(3, inicio, numero_registros)
        return RespuestaRegistros(pdu[2:], numero_registros)

    #FUNCION 4
    def ReadInputRegisters(self, inicio: int, numero_registros: int) -> RespuestaRegistros:
        pdu = self.leer(4, inicio, numero_registros)
        return RespuestaRegistros(pdu[2:], numero_registros)


def main():
    MyCliente = ClienteModbusTCP(HOST, PORT)
    RESPONSE1 = MyCliente.ReadInputRegisters(4, 5)
    print(f'respuesta de los registros {RESPONSE1.to_int()}')
    MyCliente.cerrar()

if __name__ == "__main__":
    main()