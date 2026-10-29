"""Pruebas de modbus_tcp.py y modbus_cli.py.

Se ejecutan sin el simulador: el propio archivo levanta un servidor Modbus TCP
de prueba en un hilo, con los datos de los ejemplos del guion.

    python3 -m unittest -v test.py
"""
import contextlib
import io
import socket
import struct
import threading
import time
import unittest

import modbus_cli
from modbus_tcp import (ArgumentoInvalido, ClienteModbusSeguro, ClienteModbusTCP,
                        ErrorConexion, ErrorProtocolo, ErrorTimeout,
                        ExcepcionModbus, RespuestaBits, RespuestaRegistros)

HOST = "127.0.0.1"


# =====================================================================
#  Servidor de prueba
# =====================================================================
class ServidorPrueba:
    """Servidor Modbus TCP mínimo con tablas de 10 000 posiciones.

    modo:
      "normal"    responde según la norma
      "descartar" no responde (provoca timeout)
      "troceado"  envía la respuesta byte a byte
      "tid_malo"  responde con un Transaction ID equivocado
      "cerrar"    cierra la conexión al recibir la petición
    """
    N = 10000

    def __init__(self, modo: str = "normal"):
        self.modo = modo
        self.recibidas: list[bytes] = []      # tramas ADU recibidas, para comprobar TX
        self.coils = [0] * self.N
        self.entradas = [0] * self.N
        self.holding = [0] * self.N
        self.input = [0] * self.N
        # Datos de los ejemplos del guion
        self.coils[20:30] = [1, 0, 1, 1, 0, 0, 1, 0, 1, 1]
        self.entradas[0:5] = [1, 1, 0, 0, 1]
        self.holding[107:110] = [555, 0, 100]
        self.holding[3:9] = [0x00FE, 0x0ACD, 1, 3, 0x000D, 0x00FF]
        self.input[8] = 10

        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((HOST, 0))              # puerto libre cualquiera
        self.sock.listen()
        self.puerto = self.sock.getsockname()[1]
        threading.Thread(target=self._aceptar, daemon=True).start()

    def cerrar(self):
        self.sock.close()

    # --- red -----------------------------------------------------------
    def _aceptar(self):
        while True:
            try:
                conexion, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._atender, args=(conexion,), daemon=True).start()

    @staticmethod
    def _recibir(conexion, n):
        datos = b""
        while len(datos) < n:
            trozo = conexion.recv(n - len(datos))
            if not trozo:
                return None
            datos += trozo
        return datos

    def _atender(self, conexion):
        with conexion:
            while True:
                cabecera = self._recibir(conexion, 7)
                if cabecera is None:
                    return
                tid, proto, longitud, unidad = struct.unpack(">HHHB", cabecera)
                pdu = self._recibir(conexion, longitud - 1)
                if pdu is None:
                    return
                self.recibidas.append(cabecera + pdu)

                if self.modo == "descartar":
                    continue
                if self.modo == "cerrar":
                    return
                if self.modo == "tid_malo":
                    tid = (tid + 1000) % 65536

                respuesta = self._procesar(pdu)
                trama = struct.pack(">HHHB", tid, proto, len(respuesta) + 1, unidad) + respuesta
                if self.modo == "troceado":
                    for byte in trama:
                        conexion.sendall(bytes([byte]))
                        time.sleep(0.005)
                else:
                    conexion.sendall(trama)

    # --- lógica Modbus -------------------------------------------------
    @staticmethod
    def _empaquetar(bits):
        datos = bytearray((len(bits) + 7) // 8)
        for i, b in enumerate(bits):
            if b:
                datos[i // 8] |= 1 << (i % 8)
        return bytes(datos)

    @staticmethod
    def _desempaquetar(datos, n):
        return [(datos[i // 8] >> (i % 8)) & 1 for i in range(n)]

    @staticmethod
    def _excepcion(funcion, codigo):
        return bytes([funcion | 0x80, codigo])

    def _procesar(self, pdu):
        f = pdu[0]
        if f in (1, 2, 3, 4):
            dir_, cant = struct.unpack(">HH", pdu[1:5])
            if not 1 <= cant <= (2000 if f < 3 else 125):
                return self._excepcion(f, 3)
            if dir_ + cant > self.N:
                return self._excepcion(f, 2)
            if f in (1, 2):
                tabla = self.coils if f == 1 else self.entradas
                datos = self._empaquetar(tabla[dir_:dir_ + cant])
            else:
                tabla = self.holding if f == 3 else self.input
                datos = struct.pack(f">{cant}H", *tabla[dir_:dir_ + cant])
            return bytes([f, len(datos)]) + datos
        if f == 5:
            dir_, valor = struct.unpack(">HH", pdu[1:5])
            if valor not in (0xFF00, 0x0000):
                return self._excepcion(f, 3)
            if dir_ >= self.N:
                return self._excepcion(f, 2)
            self.coils[dir_] = 1 if valor else 0
            return pdu
        if f == 6:
            dir_, valor = struct.unpack(">HH", pdu[1:5])
            if dir_ >= self.N:
                return self._excepcion(f, 2)
            self.holding[dir_] = valor
            return pdu
        if f == 0x0F:
            dir_, cant, n = struct.unpack(">HHB", pdu[1:6])
            if n != (cant + 7) // 8 or len(pdu) != 6 + n:
                return self._excepcion(f, 3)
            if dir_ + cant > self.N:
                return self._excepcion(f, 2)
            self.coils[dir_:dir_ + cant] = self._desempaquetar(pdu[6:], cant)
            return pdu[:5]
        if f == 0x10:
            dir_, cant, n = struct.unpack(">HHB", pdu[1:6])
            if n != 2 * cant or len(pdu) != 6 + n:
                return self._excepcion(f, 3)
            if dir_ + cant > self.N:
                return self._excepcion(f, 2)
            self.holding[dir_:dir_ + cant] = struct.unpack(f">{cant}H", pdu[6:])
            return pdu[:5]
        if f == 0x17:
            dl, cl, de, ce, n = struct.unpack(">HHHHB", pdu[1:10])
            if n != 2 * ce or len(pdu) != 10 + n:
                return self._excepcion(f, 3)
            if dl + cl > self.N or de + ce > self.N:
                return self._excepcion(f, 2)
            self.holding[de:de + ce] = struct.unpack(f">{ce}H", pdu[10:])
            datos = struct.pack(f">{cl}H", *self.holding[dl:dl + cl])
            return bytes([f, len(datos)]) + datos
        return self._excepcion(f, 1)


def puerto_libre() -> int:
    """Puerto en el que no escucha nadie (para provocar ErrorConexion)."""
    s = socket.socket()
    s.bind((HOST, 0))
    puerto = s.getsockname()[1]
    s.close()
    return puerto


def hexa(texto: str) -> bytes:
    """'01 03 00 6B' -> b'\\x01\\x03\\x00\\x6b'"""
    return bytes.fromhex(texto)


# =====================================================================
#  1. Conversiones (sin red)
# =====================================================================
class TestConversiones(unittest.TestCase):

    def test_to_binary_ejemplo_guion(self):
        # 4D 03 -> coils 20..29 = 1,0,1,1,0,0,1,0,1,1
        r = RespuestaBits(hexa("4D 03"), 10)
        self.assertEqual(r.to_binary(), [1, 0, 1, 1, 0, 0, 1, 0, 1, 1])

    def test_from_binary_ejemplo_guion(self):
        # 1,0,1,1,0,0,1,1,1,0 -> CD 01 (función 0F)
        r = RespuestaBits.from_binary([1, 0, 1, 1, 0, 0, 1, 1, 1, 0])
        self.assertEqual(bytes(r), hexa("CD 01"))
        self.assertEqual(r.cantidad, 10)

    def test_ida_y_vuelta_bits(self):
        bits = [1, 0, 0, 1, 1, 1, 0, 1, 0, 0, 1, 1, 0, 1, 1, 0, 1]
        self.assertEqual(RespuestaBits.from_binary(bits).to_binary(), bits)

    def test_respuesta_sigue_siendo_bytes(self):
        r = RespuestaBits(hexa("4D 03"), 10)
        self.assertIsInstance(r, bytes)
        self.assertEqual(r.hex(" "), "4d 03")

    def test_to_int_y_to_signed(self):
        r = RespuestaRegistros(hexa("02 2B 00 00 00 64 FF FB"), 4)
        self.assertEqual(r.to_int(), [555, 0, 100, 65531])
        self.assertEqual(r.to_signed(), [555, 0, 100, -5])


# =====================================================================
#  2. Tramas: lo que se envía coincide con las TX del guion
# =====================================================================
class TestTramas(unittest.TestCase):

    def setUp(self):
        self.servidor = ServidorPrueba()
        self.cliente = ClienteModbusSeguro(HOST, self.servidor.puerto, timeout=2)

    def tearDown(self):
        self.cliente.close()
        self.servidor.cerrar()

    def assertPDUEnviada(self, pdu_esperada: str):
        """Compara la PDU de la última trama enviada y la coherencia de la MBAP."""
        trama = self.servidor.recibidas[-1]
        tid, proto, longitud, unidad = struct.unpack(">HHHB", trama[:7])
        self.assertEqual(trama[7:], hexa(pdu_esperada))
        self.assertEqual(proto, 0)
        self.assertEqual(longitud, len(hexa(pdu_esperada)) + 1)
        self.assertEqual(unidad, 0xFF)

    def test_cabecera_mbap(self):
        # MBAP del guion (con Unit ID 0xFF): TID 0, protocolo 0, Length 6
        self.assertEqual(self.cliente.CabeceraMBAP(hexa("03 00 6B 00 03")),
                         hexa("00 00 00 00 00 06 FF"))

    def test_fc01_leer_coils(self):
        self.assertEqual(self.cliente.leer_coils(20, 10), [1, 0, 1, 1, 0, 0, 1, 0, 1, 1])
        self.assertPDUEnviada("01 00 14 00 0A")

    def test_fc02_leer_entradas(self):
        self.assertEqual(self.cliente.leer_entradas_discretas(0, 5), [1, 1, 0, 0, 1])
        self.assertPDUEnviada("02 00 00 00 05")

    def test_fc03_leer_holding(self):
        self.assertEqual(self.cliente.leer_holding_registers(107, 3), [555, 0, 100])
        self.assertPDUEnviada("03 00 6B 00 03")

    def test_fc04_leer_input(self):
        self.assertEqual(self.cliente.leer_input_registers(8, 1), [10])
        self.assertPDUEnviada("04 00 08 00 01")

    def test_fc05_escribir_coil(self):
        self.cliente.escribir_coil(172, 1)
        self.assertPDUEnviada("05 00 AC FF 00")
        self.assertEqual(self.servidor.coils[172], 1)
        self.cliente.escribir_coil(172, 0)
        self.assertPDUEnviada("05 00 AC 00 00")
        self.assertEqual(self.servidor.coils[172], 0)

    def test_fc06_escribir_registro(self):
        self.cliente.escribir_registro(1, 3)
        self.assertPDUEnviada("06 00 01 00 03")
        self.assertEqual(self.servidor.holding[1], 3)

    def test_fc06_negativo_complemento_a_2(self):
        self.cliente.escribir_registro(1, -5)
        self.assertPDUEnviada("06 00 01 FF FB")
        self.assertEqual(self.cliente.ReadHoldingRegisters(1, 1).to_signed(), [-5])

    def test_fc0F_escribir_coils(self):
        bits = [1, 0, 1, 1, 0, 0, 1, 1, 1, 0]
        self.cliente.escribir_coils(19, bits)
        self.assertPDUEnviada("0F 00 13 00 0A 02 CD 01")
        self.assertEqual(self.servidor.coils[19:29], bits)

    def test_fc0F_bits_que_empiezan_por_cero(self):
        self.cliente.escribir_coils(30, [0, 0, 1, 1])
        self.assertEqual(self.cliente.leer_coils(30, 4), [0, 0, 1, 1])

    def test_fc10_escribir_registros(self):
        self.cliente.escribir_registros(1, [0x000A, 0x0102])
        self.assertPDUEnviada("10 00 01 00 02 04 00 0A 01 02")
        self.assertEqual(self.servidor.holding[1:3], [10, 258])

    def test_fc17_leer_escribir(self):
        leidos = self.cliente.leer_escribir_registros(3, 6, 14, [0xFF, 0xFF, 0xFF])
        self.assertPDUEnviada("17 00 03 00 06 00 0E 00 03 06 00 FF 00 FF 00 FF")
        self.assertEqual(leidos, [0x00FE, 0x0ACD, 1, 3, 0x000D, 0x00FF])
        self.assertEqual(self.servidor.holding[14:17], [0xFF, 0xFF, 0xFF])

    def test_transaction_id_se_incrementa_y_da_la_vuelta(self):
        self.cliente.leer_coils(20, 1)
        self.cliente.leer_coils(20, 1)
        tids = [struct.unpack(">H", t[:2])[0] for t in self.servidor.recibidas]
        self.assertEqual(tids, [0, 1])
        self.cliente.TransactionID = 65535
        self.cliente.leer_coils(20, 1)
        self.assertEqual(self.cliente.TransactionID, 0)

    def test_unidad_configurable(self):
        cliente = ClienteModbusSeguro(HOST, self.servidor.puerto, unidad=1, timeout=2)
        cliente.leer_coils(20, 1)
        cliente.close()
        self.assertEqual(self.servidor.recibidas[-1][6], 1)


# =====================================================================
#  3. Errores
# =====================================================================
class TestErrores(unittest.TestCase):

    def crear(self, modo="normal", timeout=2):
        self.servidor = ServidorPrueba(modo)
        self.addCleanup(self.servidor.cerrar)
        cliente = ClienteModbusSeguro(HOST, self.servidor.puerto, timeout=timeout)
        self.addCleanup(cliente.close)
        return cliente

    def test_excepcion_direccion_ilegal(self):
        cliente = self.crear()
        with self.assertRaises(ExcepcionModbus) as ctx:
            cliente.leer_holding_registers(9999, 2)
        self.assertEqual(ctx.exception.funcion, 0x03)
        self.assertEqual(ctx.exception.codigo, 0x02)
        self.assertEqual(ctx.exception.nombre, "ILLEGAL DATA ADDRESS")

    def test_cliente_sigue_funcionando_tras_excepcion(self):
        cliente = self.crear()
        with self.assertRaises(ExcepcionModbus):
            cliente.leer_holding_registers(10000 - 1, 2)
        self.assertEqual(cliente.leer_holding_registers(107, 3), [555, 0, 100])

    def test_excepcion_funcion_ilegal(self):
        cliente = self.crear()
        with self.assertRaises(ExcepcionModbus) as ctx:
            cliente.ejecutar(hexa("2B 00 00"))      # función que el servidor no implementa
        self.assertEqual(ctx.exception.codigo, 0x01)
        self.assertEqual(ctx.exception.nombre, "ILLEGAL FUNCTION")

    def test_timeout(self):
        cliente = self.crear("descartar", timeout=0.5)
        with self.assertRaises(ErrorTimeout):
            cliente.leer_coils(20, 1)

    def test_error_conexion_puerto_cerrado(self):
        with self.assertRaises(ErrorConexion):
            ClienteModbusSeguro(HOST, puerto_libre(), timeout=1)

    def test_error_conexion_servidor_cierra(self):
        cliente = self.crear("cerrar")
        with self.assertRaises(ErrorConexion):
            cliente.leer_coils(20, 1)

    def test_error_protocolo_transaction_id(self):
        cliente = self.crear("tid_malo")
        with self.assertRaises(ErrorProtocolo):
            cliente.leer_coils(20, 1)

    def test_respuesta_troceada(self):
        cliente = self.crear("troceado")
        self.assertEqual(cliente.leer_holding_registers(107, 3), [555, 0, 100])

    def test_argumentos_fuera_de_rango(self):
        cliente = self.crear()
        casos = [
            lambda: cliente.leer_holding_registers(0, 0),
            lambda: cliente.leer_holding_registers(0, 126),
            lambda: cliente.leer_coils(0, 2001),
            lambda: cliente.leer_coils(70000, 1),
            lambda: cliente.escribir_coil(1, 2),
            lambda: cliente.escribir_registro(1, 70000),
            lambda: cliente.escribir_registro(1, -40000),
            lambda: cliente.escribir_registros(1, [1] * 124),
            lambda: cliente.escribir_coils(1, [1, 2]),
        ]
        for caso in casos:
            with self.subTest(caso=caso):
                with self.assertRaises(ArgumentoInvalido):
                    caso()
        # Ninguna de esas peticiones debe haber llegado al servidor
        self.assertEqual(self.servidor.recibidas, [])


# =====================================================================
#  4. Programa modbus_cli.py
# =====================================================================
class TestCLI(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.servidor = ServidorPrueba()
        cls.servidor_descarta = ServidorPrueba("descartar")

    @classmethod
    def tearDownClass(cls):
        cls.servidor.cerrar()
        cls.servidor_descarta.cerrar()

    def cli(self, *argumentos, puerto=None):
        """Ejecuta modbus_cli.main y devuelve (salida, código de salida)."""
        puerto = puerto or self.servidor.puerto
        argv = ["--puerto", str(puerto), "--timeout", "0.5", *argumentos]
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            try:
                codigo = modbus_cli.main(argv)
            except SystemExit as e:              # errores de argparse
                codigo = e.code
        return salida.getvalue(), codigo

    def test_leer_coils(self):
        salida, codigo = self.cli("leer-coils", "20", "3")
        self.assertEqual(codigo, 0)
        self.assertEqual(salida, "20 1\n21 0\n22 1\n")

    def test_leer_holding_formato(self):
        salida, codigo = self.cli("leer-holding", "107", "3")
        self.assertEqual(codigo, 0)
        self.assertEqual(salida, "107 555 555 0x022B\n108 0 0 0x0000\n109 100 100 0x0064\n")

    def test_leer_input(self):
        salida, codigo = self.cli("leer-input", "8", "1")
        self.assertEqual((salida, codigo), ("8 10 10 0x000A\n", 0))

    def test_escribir_registro_negativo(self):
        self.assertEqual(self.cli("escribir-registro", "50", "-5"), ("OK\n", 0))
        salida, _ = self.cli("leer-holding", "50", "1")
        self.assertEqual(salida, "50 65531 -5 0xFFFB\n")

    def test_escribir_coil(self):
        self.assertEqual(self.cli("escribir-coil", "172", "1"), ("OK\n", 0))
        self.assertEqual(self.servidor.coils[172], 1)

    def test_escribir_coils_formatos(self):
        for valores in (["1,0,1,1"], ["1", "0", "1", "1"], ["1011"]):
            with self.subTest(valores=valores):
                self.assertEqual(self.cli("escribir-coils", "40", *valores), ("OK\n", 0))
                self.assertEqual(self.servidor.coils[40:44], [1, 0, 1, 1])
                self.servidor.coils[40:44] = [0, 0, 0, 0]

    def test_escribir_registros(self):
        self.assertEqual(self.cli("escribir-registros", "60", "10", "258"), ("OK\n", 0))
        self.assertEqual(self.servidor.holding[60:62], [10, 258])

    def test_leer_escribir(self):
        salida, codigo = self.cli("leer-escribir", "3", "2", "70", "7", "8")
        self.assertEqual(codigo, 0)
        self.assertEqual(salida, "3 254 254 0x00FE\n4 2765 2765 0x0ACD\n")
        self.assertEqual(self.servidor.holding[70:72], [7, 8])

    def test_argumento_invalido(self):
        for argumentos in (["leer-holding", "0", "126"],
                           ["escribir-coil", "1", "2"],
                           ["leer-coils", "abc", "1"],
                           ["--unidad", "300", "leer-coils", "0", "1"],
                           []):
            with self.subTest(argumentos=argumentos):
                salida, codigo = self.cli(*argumentos)
                self.assertEqual(codigo, 2)
                self.assertTrue(salida.startswith("ARGUMENTO INVALIDO: "), salida)

    def test_excepcion(self):
        self.assertEqual(self.cli("leer-holding", "9999", "2"),
                         ("EXCEPCION 0x02 ILLEGAL DATA ADDRESS\n", 3))

    def test_timeout(self):
        self.assertEqual(self.cli("leer-coils", "0", "1", puerto=self.servidor_descarta.puerto),
                         ("TIMEOUT\n", 4))

    def test_error_conexion(self):
        salida, codigo = self.cli("leer-coils", "0", "1", puerto=puerto_libre())
        self.assertEqual(codigo, 5)
        self.assertTrue(salida.startswith("ERROR DE CONEXION: "), salida)


if __name__ == "__main__":
    unittest.main(verbosity=2)
