# Cliente Modbus TCP

Cliente **Modbus TCP** escrito en Python con programación orientada a objetos. Construye, envía y valida cada trama byte a byte, **sin bibliotecas Modbus**: solo usa la biblioteca estándar (`socket`, `struct`, `argparse`).

Proyecto de la asignatura *Redes de Comunicación Industriales* del máster en la Universidad de Deusto.

**Autor:** Angel Ardila

---

## Características

- 9 funciones Modbus: lectura, escritura simple, escritura múltiple y lectura/escritura combinada.
- Cabecera MBAP construida y validada (Transaction ID, Protocol ID, Length y Unit ID).
- Recepción exacta de tramas: las respuestas que llegan partidas se reconstruyen.
- Excepciones propias para cada tipo de fallo. El cliente sigue funcionando después de una excepción Modbus.
- Programa de línea de órdenes con traza de las tramas en hexadecimal.
- 40 pruebas automáticas que no necesitan servidor externo.

## Archivos

| Archivo | Descripción |
|---|---|
| `modbus_tcp.py` | Biblioteca: tramas, envío, recepción y validación. |
| `modbus_cli.py` | Programa de línea de órdenes: ejecuta una petición y muestra el resultado. |
| `test.py` | Pruebas automáticas con `unittest`. |

## Requisitos

- Python 3.10 o superior.
- Un servidor Modbus TCP, por ejemplo el SimuladorModbus del laboratorio (puerto 5020).

## Funciones implementadas

| Código | Función | Orden del CLI |
|:---:|---|---|
| `01` | Leer coils | `leer-coils` |
| `02` | Leer entradas discretas | `leer-entradas` |
| `03` | Leer holding registers | `leer-holding` |
| `04` | Leer input registers | `leer-input` |
| `05` | Escribir una coil | `escribir-coil` |
| `06` | Escribir un registro | `escribir-registro` |
| `0F` | Escribir varias coils | `escribir-coils` |
| `10` | Escribir varios registros | `escribir-registros` |
| `17` | Leer y escribir registros | `leer-escribir` |

## Estructura de la biblioteca

```
RespuestaModbus (bytes)       Datos de una respuesta + cantidad pedida
├── RespuestaBits             to_binary() / from_binary()
└── RespuestaRegistros        to_int() / to_signed()

ClienteModbusTCP (socket)     Conexión, cabecera MBAP, envío/recepción, un método por función
└── ClienteModbusSeguro       Validación de rangos y respuestas, errores propios

ErrorModbus (Exception)
├── ExcepcionModbus           El servidor responde con una excepción (código y nombre)
├── ErrorTimeout              El servidor no responde a tiempo
├── ErrorConexion             No se puede conectar o el servidor cierra la conexión
├── ErrorProtocolo            La respuesta no cumple el protocolo
└── ArgumentoInvalido         Un parámetro está fuera de rango
```

## Uso de la biblioteca

```python
from modbus_tcp import ClienteModbusSeguro, ExcepcionModbus

cliente = ClienteModbusSeguro("127.0.0.1", 5020, unidad=1, timeout=2)

print(cliente.leer_holding_registers(107, 3))   # [555, 0, 100]
cliente.escribir_coil(172, 1)

try:
    cliente.leer_holding_registers(9999, 2)
except ExcepcionModbus as e:
    print(e.codigo, e.nombre)                   # 2 ILLEGAL DATA ADDRESS

cliente.close()
```

## Uso del programa

```bash
python3 modbus_cli.py [--ip IP] [--puerto P] [--unidad U] [--timeout S] [--traza] ORDEN ARGUMENTOS
```

Las opciones van siempre **antes** de la orden.

| Opción | Por defecto | Descripción |
|---|---|---|
| `--ip` | `127.0.0.1` | Dirección del servidor |
| `--puerto` | `5020` | Puerto TCP |
| `--unidad` | `255` | Unit ID |
| `--timeout` | `3` | Segundos de espera |
| `--traza` | desactivada | Muestra las tramas TX/RX en hexadecimal |

### Ejemplos

```bash
python3 modbus_cli.py leer-coils 20 10
python3 modbus_cli.py --traza leer-holding 107 3
python3 modbus_cli.py escribir-coil 172 1
python3 modbus_cli.py escribir-registro 1 -5
python3 modbus_cli.py escribir-coils 19 1 0 1 1 0 0 1 1 1 0
python3 modbus_cli.py escribir-registros 1 0x000A 0x0102
python3 modbus_cli.py leer-escribir 3 6 14 0xFF 0xFF 0xFF
```

Con `--traza`:

```
$ python3 modbus_cli.py --traza leer-holding 107 3
TX: 00 00 00 00 00 06 FF 03 00 6B 00 03
RX: 00 00 00 00 00 09 FF 03 06 02 2B 00 00 00 64
107 555 555 0x022B
108 0 0 0x0000
109 100 100 0x0064
```

Los valores se pueden separar por espacios o comas, y admiten decimal o hexadecimal (`0x..`). Las coils también se pueden escribir juntas: `1011`.

### Códigos de salida

| Código | Significado |
|:---:|---|
| `0` | Correcto |
| `2` | Argumento inválido |
| `3` | Excepción Modbus |
| `4` | Timeout |
| `5` | Error de conexión |
| `6` | Error de protocolo |

## Pruebas

```bash
python3 -m unittest -v test.py
```

Las pruebas levantan su propio servidor Modbus de prueba en un hilo, así que no necesitan el simulador.
