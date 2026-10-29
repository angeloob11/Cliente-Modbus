"""modbus_cli.py: ejecuta una sola petición Modbus TCP con la biblioteca propia.

Uso:
    python3 modbus_cli.py [--ip IP] [--puerto P] [--unidad U] [--timeout S] [--traza]
                          ORDEN ARGUMENTOS

Códigos de salida: 0 OK, 2 argumento inválido, 3 excepción Modbus,
4 timeout, 5 error de conexión, 6 error de protocolo.
"""
import argparse
import sys

from modbus_tcp import (AUTOR, ArgumentoInvalido, ClienteModbusSeguro,
                        ErrorConexion, ErrorProtocolo, ErrorTimeout,
                        ExcepcionModbus)

SALIDA_OK = 0
SALIDA_ARGUMENTO = 2
SALIDA_EXCEPCION = 3
SALIDA_TIMEOUT = 4
SALIDA_CONEXION = 5
SALIDA_PROTOCOLO = 6


class ParserModbus(argparse.ArgumentParser):
    """argparse que informa de los errores con el formato del guion."""

    def error(self, message):
        print(f"ARGUMENTO INVALIDO: {message}")
        sys.exit(SALIDA_ARGUMENTO)


def entero(texto: str) -> int:
    """Admite decimal, hexadecimal (0x..) o negativo."""
    try:
        return int(texto, 0)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{texto}' no es un entero")


def lista_valores(textos: list[str]) -> list[int]:
    """Acepta '10 258', '10,258' y, para bits, una cadena como '1011'."""
    partes = [p for t in textos for p in t.replace(",", " ").split()]
    if len(partes) == 1 and len(partes[0]) > 1 and set(partes[0]) <= {"0", "1"}:
        return [int(c) for c in partes[0]]
    try:
        return [int(p, 0) for p in partes]
    except ValueError:
        raise ArgumentoInvalido(f"valores no válidos: {' '.join(textos)}")


def crear_parser() -> ParserModbus:
    p = ParserModbus(prog="modbus_cli.py",
                     description=f"Cliente Modbus TCP (autor: {AUTOR})")
    p.add_argument("--ip", default="127.0.0.1")
    p.add_argument("--puerto", type=entero, default=5020)
    p.add_argument("--unidad", type=entero, default=0xFF)
    p.add_argument("--timeout", type=float, default=3.0)
    p.add_argument("--traza", action="store_true", help="muestra TX/RX en hexadecimal")

    ordenes = p.add_subparsers(dest="orden", required=True, parser_class=ParserModbus)
    for nombre in ("leer-coils", "leer-entradas", "leer-holding", "leer-input"):
        o = ordenes.add_parser(nombre)
        o.add_argument("direccion", type=entero)
        o.add_argument("cantidad", type=entero)
    for nombre in ("escribir-coil", "escribir-registro"):
        o = ordenes.add_parser(nombre)
        o.add_argument("direccion", type=entero)
        o.add_argument("valor", type=entero)
    for nombre in ("escribir-coils", "escribir-registros"):
        o = ordenes.add_parser(nombre)
        o.add_argument("direccion", type=entero)
        o.add_argument("valores", nargs="+")
    o = ordenes.add_parser("leer-escribir")
    o.add_argument("dir_lectura", type=entero)
    o.add_argument("cantidad", type=entero)
    o.add_argument("dir_escritura", type=entero)
    o.add_argument("valores", nargs="+")
    return p


def imprimir_bits(inicio: int, bits: list[int]) -> None:
    for i, b in enumerate(bits):
        print(f"{inicio + i} {b}")


def imprimir_registros(inicio: int, valores: list[int]) -> None:
    for i, v in enumerate(valores):
        con_signo = v - 0x10000 if v >= 0x8000 else v
        print(f"{inicio + i} {v} {con_signo} 0x{v:04X}")


def ejecutar_orden(cliente: ClienteModbusSeguro, a: argparse.Namespace) -> None:
    orden = a.orden
    if orden == "leer-coils":
        imprimir_bits(a.direccion, cliente.leer_coils(a.direccion, a.cantidad))
    elif orden == "leer-entradas":
        imprimir_bits(a.direccion, cliente.leer_entradas_discretas(a.direccion, a.cantidad))
    elif orden == "leer-holding":
        imprimir_registros(a.direccion, cliente.leer_holding_registers(a.direccion, a.cantidad))
    elif orden == "leer-input":
        imprimir_registros(a.direccion, cliente.leer_input_registers(a.direccion, a.cantidad))
    elif orden == "escribir-coil":
        cliente.escribir_coil(a.direccion, a.valor)
        print("OK")
    elif orden == "escribir-registro":
        cliente.escribir_registro(a.direccion, a.valor)
        print("OK")
    elif orden == "escribir-coils":
        cliente.escribir_coils(a.direccion, lista_valores(a.valores))
        print("OK")
    elif orden == "escribir-registros":
        cliente.escribir_registros(a.direccion, lista_valores(a.valores))
        print("OK")
    elif orden == "leer-escribir":
        leidos = cliente.leer_escribir_registros(a.dir_lectura, a.cantidad,
                                                 a.dir_escritura, lista_valores(a.valores))
        imprimir_registros(a.dir_lectura, leidos)


def validar_previo(a: argparse.Namespace) -> None:
    """Comprueba los argumentos antes de conectar, para no abrir el socket en balde."""
    from modbus_tcp import validar_rango
    validar_rango("puerto", a.puerto, 1, 65535)
    validar_rango("unidad", a.unidad, 0, 255)
    if a.timeout <= 0:
        raise ArgumentoInvalido(f"timeout={a.timeout} debe ser positivo")


def main(argv=None) -> int:
    args = crear_parser().parse_args(argv)
    cliente = None
    try:
        validar_previo(args)
        cliente = ClienteModbusSeguro(args.ip, args.puerto, unidad=args.unidad,
                                      timeout=args.timeout, traza=args.traza)
        ejecutar_orden(cliente, args)
        return SALIDA_OK
    except ArgumentoInvalido as e:
        print(f"ARGUMENTO INVALIDO: {e}")
        return SALIDA_ARGUMENTO
    except ExcepcionModbus as e:
        print(f"EXCEPCION 0x{e.codigo:02X} {e.nombre}")
        return SALIDA_EXCEPCION
    except ErrorTimeout:
        print("TIMEOUT")
        return SALIDA_TIMEOUT
    except ErrorConexion as e:
        print(f"ERROR DE CONEXION: {e}")
        return SALIDA_CONEXION
    except ErrorProtocolo as e:
        print(f"ERROR DE PROTOCOLO: {e}")
        return SALIDA_PROTOCOLO
    finally:
        if cliente is not None:
            cliente.close()


if __name__ == "__main__":
    sys.exit(main())
