import socket
import struct
import sys

AUTOR = "Angel Ardila"

HOST = "127.0.0.1"
PORT = 502
PROTOCOL_ID = 0
UNIT_ID = 0XFF
ON = b'\xff\x00'
OFF  = b'\x00\x00'

class RespuestaModbus(bytes):
    def __new__(cls, datos: bytes, cantidad: int):
        obj = super().__new__(cls, datos)
        obj.cantidad = cantidad
        return obj


class RespuestaBits(RespuestaModbus):
    def to_binary(self) -> list[int]:
        return [(self[i // 8] >> (i % 8)) & 1
                for i in range(self.cantidad)]
    
    @classmethod
    def from_binary(cls, bits: list[int]) -> "RespuestaBits":
        datos = bytearray((len(bits) + 7) // 8)
        for i, bit in enumerate(bits):
            if bit:
                datos[i // 8] |= 1 << (i % 8)
        return cls(bytes(datos), len(bits))


class RespuestaRegistros(RespuestaModbus):
    def to_int(self) -> list[int]:
        return list(struct.unpack(f">{self.cantidad}H", self))

    def to_signed(self) -> list[int]:
        return list(struct.unpack(f">{self.cantidad}h", self))



class ClienteModbusTCP(socket.socket):
    def __init__(self, HOST:str, PORT:int, unidad:int = UNIT_ID, timeout:float = 3.0, traza:bool = False):
        super().__init__(socket.AF_INET, socket.SOCK_STREAM)
        self.HOST = HOST
        self.PORT = PORT
        self.unidad = unidad          
        self.traza = traza            
        self.TransactionID = 0
        self.ultima_cabecera = None   
        self.settimeout(timeout)      
        self.conectar()

    def conectar(self)->None:
        self.connect((self.HOST, self.PORT))

    def recibir(self, n:int)->bytes:
        datos = b''
        while len(datos) < n:
            trozo = self.recv(n - len(datos))
            if not trozo:
                raise ConnectionError("el servidor ha cerrado la conexión")
            datos += trozo
        return datos

    def ejecutar(self, mensaje:bytes)->bytes:
        MBAP = self.CabeceraMBAP(mensaje)
        datos = MBAP + mensaje 
        if self.traza:
            print('TX:', datos.hex(' ').upper(), file=sys.stderr)
        self.sendall(datos)
        self.TransactionID = (self.TransactionID + 1) % 65536   # CAMBIO: vuelve a 0 tras 65535
        cabecera = self.recibir(7)
        MBAP_recibido = struct.unpack('>HHHB', cabecera)
        pdu = self.recibir(MBAP_recibido[2]-1)
        self.ultima_cabecera = MBAP_recibido
        if self.traza:
            print('RX:', (cabecera + pdu).hex(' ').upper(), file=sys.stderr)
        return pdu

    def leer(self, function:int, start:int, cantidad:int)->bytes:
        return self.ejecutar(function.to_bytes(1, 'big')+start.to_bytes(2, 'big')+cantidad.to_bytes(2,'big'))


    def cerrar(self)->None:
        self.close()

    def CabeceraMBAP(self, msg:bytes)->bytes:
        return struct.pack('>H',self.TransactionID)+struct.pack('>H',PROTOCOL_ID)+struct.pack('>H',len(msg)+1)+struct.pack('>B',self.unidad)

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

    #FUNCION 5 
    def WriteSingelCoil(self, coil:int, value:bool)->bytes:
        input = ON if value else OFF
        pdu = self.ejecutar(b'\x05'+coil.to_bytes(2, 'big')+input)
        return (struct.unpack('>H', pdu[1:3])[0], True if pdu[3:5] == ON else False if pdu[3:5] == OFF else "ERR")


    #FUNCION 6
    def WriteSingelRegister(self, coil:int, value:int)->bytes:
        pdu = self.ejecutar(b'\x06'+coil.to_bytes(2, 'big')+value.to_bytes(2, 'big'))
        return (struct.unpack('>H',pdu[1:3])[0],struct.unpack('>H',pdu[3:5])[0])

    #FUNCION 15 OF
    def WriteMultipleCoils(self, coil:int,cantidad:int, value:int)->bytes:
        CoilsVals = RespuestaBits.from_binary([int(i) for i in str(value)])
        pdu = self.ejecutar(b'\x0f'+coil.to_bytes(2, 'big')+cantidad.to_bytes(2, 'big')+len(CoilsVals).to_bytes(1, 'big')+CoilsVals)
        return (pdu)

    #FUNCION 16 10
    def WriteMultipleRegisters(self, coil:int,cantidad:int, value:list[int])->bytes:
        CoilsVals = bytearray()
        for i in range(len(value)):
            CoilsVals += value[i].to_bytes(2,'big')
        pdu = self.ejecutar(b'\x10'+coil.to_bytes(2, 'big')+cantidad.to_bytes(2, 'big')+len(CoilsVals).to_bytes(1, 'big')+CoilsVals)
        return (pdu)

    #FUNCION 23 17
    def WriteReadMultipleRegs(self,coilRead:int,CantidadRead:int,coilWrite:int,CantidadWrite:int,value:list[int]):
        CoilsVals = bytearray()
        for i in range(len(value)):
            CoilsVals += value[i].to_bytes(2,'big')
        pdu = self.ejecutar(b'\x17'+coilRead.to_bytes(2, 'big')+CantidadRead.to_bytes(2, 'big')+coilWrite.to_bytes(2, 'big')+CantidadWrite.to_bytes(2, 'big')+len(CoilsVals).to_bytes(1, 'big')+CoilsVals)
        return (pdu)

NOMBRES_EXCEPCION = {
    0x01: "ILLEGAL FUNCTION",
    0x02: "ILLEGAL DATA ADDRESS",
    0x03: "ILLEGAL DATA VALUE",
    0x04: "SERVER DEVICE FAILURE",
    0x05: "ACKNOWLEDGE",
    0x06: "SERVER DEVICE BUSY",
    0x08: "MEMORY PARITY ERROR",
    0x0A: "GATEWAY PATH UNAVAILABLE",
    0x0B: "GATEWAY TARGET DEVICE FAILED TO RESPOND",
}


class ErrorModbus(Exception):
    """Clase base de todos los errores de la biblioteca."""


class ExcepcionModbus(ErrorModbus):
    """El servidor ha respondido con función + 0x80 y un código de excepción."""

    def __init__(self, funcion: int, codigo: int):
        self.funcion = funcion
        self.codigo = codigo
        self.nombre = NOMBRES_EXCEPCION.get(codigo, "DESCONOCIDA")
        super().__init__(f"EXCEPCION 0x{codigo:02X} {self.nombre}")


class ErrorTimeout(ErrorModbus):
    """El servidor no ha respondido a tiempo."""


class ErrorConexion(ErrorModbus):
    """No se pudo conectar, o el servidor cerró la conexión."""


class ErrorProtocolo(ErrorModbus):
    """La respuesta no cumple el protocolo (IDs, longitudes, eco...)."""


class ArgumentoInvalido(ErrorModbus, ValueError):
    """Un parámetro de la petición está fuera de rango."""


def validar_rango(nombre: str, valor: int, minimo: int, maximo: int) -> int:
    """Lanza ArgumentoInvalido si valor no está en [minimo, maximo]."""
    if not isinstance(valor, int) or not (minimo <= valor <= maximo):
        raise ArgumentoInvalido(f"{nombre}={valor} fuera de rango ({minimo}-{maximo})")
    return valor


def a_complemento2(valor: int) -> int:
    """Convierte -32768..65535 a 0..65535 (los negativos en complemento a 2)."""
    validar_rango("valor", valor, -32768, 65535)
    return valor & 0xFFFF


class ClienteModbusSeguro(ClienteModbusTCP):
    """ClienteModbusTCP que traduce los fallos a errores propios y valida
    cada respuesta antes de devolverla."""

    def conectar(self) -> None:
        try:
            super().conectar()
        except OSError as e:
            raise ErrorConexion(f"{self.HOST}:{self.PORT}: {e.strerror or e}") from None

    def ejecutar(self, mensaje: bytes) -> bytes:
        if not 1 <= len(mensaje) <= 253:
            raise ArgumentoInvalido(f"PDU de {len(mensaje)} bytes (máximo 253)")
        tid_enviado = self.TransactionID
        try:
            pdu = super().ejecutar(mensaje)
        except socket.timeout:
            raise ErrorTimeout("el servidor no ha respondido") from None
        except OSError as e:
            raise ErrorConexion(str(e)) from None

        # La trama ya está leída entera: aunque lancemos un error,
        # el socket queda limpio y el cliente puede seguir usándose.
        tid, protocolo, longitud, _ = self.ultima_cabecera
        if not 2 <= longitud <= 254:
            raise ErrorProtocolo(f"Length={longitud} imposible")
        if tid != tid_enviado:
            raise ErrorProtocolo(f"Transaction ID {tid}, se esperaba {tid_enviado}")
        if protocolo != 0:
            raise ErrorProtocolo(f"Protocol ID {protocolo}, se esperaba 0")

        funcion = mensaje[0]
        if pdu[0] == funcion | 0x80:
            if len(pdu) != 2:
                raise ErrorProtocolo("respuesta de excepción con longitud incorrecta")
            raise ExcepcionModbus(funcion, pdu[1])
        if pdu[0] != funcion:
            raise ErrorProtocolo(f"función 0x{pdu[0]:02X}, se esperaba 0x{funcion:02X}")

        self._validar_respuesta(mensaje, pdu)
        return pdu

    @staticmethod
    def _validar_respuesta(peticion: bytes, pdu: bytes) -> None:
        """Comprueba la forma de la respuesta según la función."""
        funcion = peticion[0]
        if funcion in (0x05, 0x06):                     # eco exacto
            if pdu != peticion:
                raise ErrorProtocolo("el eco no coincide con la petición")
        elif funcion in (0x0F, 0x10):                   # dirección + cantidad
            if pdu != peticion[:5]:
                raise ErrorProtocolo("la confirmación no coincide con la petición")
        elif funcion in (0x01, 0x02, 0x03, 0x04, 0x17):  # contador + datos
            if len(pdu) < 2 or pdu[1] != len(pdu) - 2:
                raise ErrorProtocolo("el número de bytes no coincide con los datos")
            if funcion == 0x17:
                cantidad = struct.unpack(">H", peticion[3:5])[0]
                if pdu[1] != 2 * cantidad:
                    raise ErrorProtocolo(f"se esperaban {2 * cantidad} bytes, llegaron {pdu[1]}")

    def leer(self, function: int, start: int, cantidad: int) -> bytes:
        validar_rango("direccion", start, 0, 65535)
        maximo = 2000 if function in (1, 2) else 125
        validar_rango("cantidad", cantidad, 1, maximo)
        pdu = super().leer(function, start, cantidad)
        esperado = (cantidad + 7) // 8 if function in (1, 2) else 2 * cantidad
        if pdu[1] != esperado:
            raise ErrorProtocolo(f"se esperaban {esperado} bytes, llegaron {pdu[1]}")
        return pdu

    # --- Atajos con los nombres del guion -----------------------------
    def leer_coils(self, direccion: int, cantidad: int) -> list[int]:
        return self.LeerCoils(direccion, cantidad).to_binary()

    def leer_entradas_discretas(self, direccion: int, cantidad: int) -> list[int]:
        return self.LeerDiscreteInputs(direccion, cantidad).to_binary()

    def leer_holding_registers(self, direccion: int, cantidad: int) -> list[int]:
        return self.ReadHoldingRegisters(direccion, cantidad).to_int()

    def leer_input_registers(self, direccion: int, cantidad: int) -> list[int]:
        return self.ReadInputRegisters(direccion, cantidad).to_int()

    def escribir_coil(self, direccion: int, valor: int) -> None:
        validar_rango("direccion", direccion, 0, 65535)
        validar_rango("valor", int(valor), 0, 1)
        self.WriteSingelCoil(direccion, bool(valor))

    def escribir_registro(self, direccion: int, valor: int) -> None:
        validar_rango("direccion", direccion, 0, 65535)
        self.WriteSingelRegister(direccion, a_complemento2(valor))

    def escribir_coils(self, direccion: int, valores: list[int]) -> None:
        validar_rango("direccion", direccion, 0, 65535)
        validar_rango("cantidad", len(valores), 1, 1968)
        for v in valores:
            validar_rango("bit", v, 0, 1)
        # WriteMultipleCoils hace str(value): con un str no se pierden ceros
        self.WriteMultipleCoils(direccion, len(valores), "".join(map(str, valores)))

    def escribir_registros(self, direccion: int, valores: list[int]) -> None:
        validar_rango("direccion", direccion, 0, 65535)
        validar_rango("cantidad", len(valores), 1, 123)
        self.WriteMultipleRegisters(direccion, len(valores),
                                    [a_complemento2(v) for v in valores])

    def leer_escribir_registros(self, dir_lectura: int, cant_lectura: int,
                                dir_escritura: int, valores: list[int]) -> list[int]:
        validar_rango("direccion de lectura", dir_lectura, 0, 65535)
        validar_rango("cantidad de lectura", cant_lectura, 1, 125)
        validar_rango("direccion de escritura", dir_escritura, 0, 65535)
        validar_rango("cantidad de escritura", len(valores), 1, 121)
        pdu = self.WriteReadMultipleRegs(dir_lectura, cant_lectura, dir_escritura,
                                         len(valores), [a_complemento2(v) for v in valores])
        return RespuestaRegistros(pdu[2:], cant_lectura).to_int()




def main():
    MyCliente = ClienteModbusTCP(HOST, PORT)
    RESPONSE1 = MyCliente.WriteReadMultipleRegs(3,6,14,3,[255,255,255])
    print(f'respuesta de los registros {RESPONSE1}')
    MyCliente.cerrar()

if __name__ == "__main__":
    main()