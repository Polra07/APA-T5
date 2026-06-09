"""
Tarea: Sonido estéreo y ficheros WAVE
Alumno: Pol Ramirez Sanchez

Este módulo proporciona funciones avanzadas para la manipulación y procesamiento 
de archivos de audio digital en formato WAVE binario sin el uso de librerías externas,
utilizando exclusivamente el módulo estándar 'struct'. Permite la conversión de
señales estéreo a monofónicas en distintas modalidades (canales independientes, 
semisuma o semidiferencia), la reconstrucción estéreo a partir de dos archivos mono,
así como la codificación estéreo esteganográfica/compatible en contenedores de 32 bits
y su posterior decodificación.
"""

import struct


def leer_cabecera(fichero):
    """
    Lee y valida la cabecera de 44 bytes de un archivo WAVE PCM binario.

    Argumentos:
    fichero -- Objeto de archivo binario abierto en modo lectura ('rb').

    Salida:
    dict -- Diccionario con los parámetros extraídos y parseados de la cabecera.
    """
    datos_cabecera = fichero.read(44)
    if len(datos_cabecera) < 44:
        raise ValueError("El archivo no contiene una cabecera WAVE completa de 44 bytes.")

    # Desempaquetado según la estructura estándar del formato RIFF / WAVE PCM
    # < (Little Endian), 4s (ChunkID), I (ChunkSize), 4s (Format), 4s (Subchunk1ID)...
    campos = struct.unpack("<4sI4s4sIHHIIHH4sI", datos_cabecera)

    if campos[0] != b"RIFF" or campos[2] != b"WAVE" or campos[3] != b"fmt ":
        raise TypeError("Formato de archivo no válido. No es un archivo RIFF/WAVE estándar.")

    cabecera_dict = {
        "ChunkID": campos[0],
        "ChunkSize": campos[1],
        "Format": campos[2],
        "Subchunk1ID": campos[3],
        "Subchunk1Size": campos[4],
        "AudioFormat": campos[5],
        "NumChannels": campos[6],
        "SampleRate": campos[7],
        "ByteRate": campos[8],
        "BlockAlign": campos[9],
        "BitsPerSample": campos[10],
        "Subchunk2ID": campos[11],
        "Subchunk2Size": campos[12],
    }

    if cabecera_dict["AudioFormat"] != 1:
        raise TypeError("Solo se admite codificación PCM lineal sin compresión.")

    return cabecera_dict


def escribir_cabecera(
    fichero, num_canales, sample_rate, bits_per_sample, num_muestras_canal
):
    """
    Genera y escribe dinámicamente una cabecera estructurada WAVE PCM válida
    calculando todos los campos binarios requeridos de forma correcta.
    """
    bytes_per_sample = bits_per_sample // 8
    block_align = num_canales * bytes_per_sample
    byte_rate = sample_rate * block_align
    subchunk2_size = num_muestras_canal * block_align
    chunk_size = 36 + subchunk2_size

    cabecera_empaquetada = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        chunk_size,
        b"WAVE",
        b"fmt ",
        16,  # Subchunk1Size fijo para PCM
        1,  # AudioFormat (1 = PCM)
        num_canales,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b"data",
        subchunk2_size,
    )
    fichero.write(cabecera_empaquetada)


def estereo2mono(ficEste, ficMono, canal=2):
    """
    Lee una señal estéreo de 16 bits y genera un archivo monofónico de 16 bits.

    Argumentos:
    ficEste -- Ruta del archivo estéreo de entrada.
    ficMono -- Ruta del archivo monofónico resultante de salida.
    canal   -- Modo de conversión:
               0: Extrae canal izquierdo (L)
               1: Extrae canal derecho (R)
               2: Calcula semisuma (L + R) // 2 [Por defecto]
               3: Calcula semidiferencia (L - R) // 2
    """
    if canal not in (0, 1, 2, 3):
        raise ValueError("El parámetro de canal debe ser un entero entre 0 y 3.")

    with open(ficEste, "rb") as f_in, open(ficMono, "wb") as f_out:
        cab = leer_cabecera(f_in)

        if cab["NumChannels"] != 2:
            raise ValueError("El archivo de entrada no es una señal estereofónica.")
        if cab["BitsPerSample"] != 16:
            raise TypeError("Esta función solo soporta audio estéreo de 16 bits.")

        # Leer los datos de audio restantes
        datos_raw = f_in.read(cab["Subchunk2Size"])
        num_muestras_totales = len(datos_raw) // 2
        muestras = struct.unpack(f"<{num_muestras_totales}h", datos_raw)

        # Separar canales usando rodajas (Slices) de Python sin bucles for tradicionales
        ch_izq = muestras[0::2]
        ch_der = muestras[1::2]

        # Aplicar el criterio de selección de manera pythónica mediante comprensiones
        if canal == 0:
            muestras_mono = ch_izq
        elif canal == 1:
            muestras_mono = ch_der
        elif canal == 2:
            muestras_mono = [(l + r) // 2 for l, r in zip(ch_izq, ch_der)]
        elif canal == 3:
            muestras_mono = [(l - r) // 2 for l, r in zip(ch_izq, ch_der)]

        # Escribir la nueva cabecera monofónica adaptando los campos
        escribir_cabecera(
            f_out,
            num_canales=1,
            sample_rate=cab["SampleRate"],
            bits_per_sample=16,
            num_muestras_canal=len(muestras_mono),
        )

        # Empaquetar y escribir las muestras resultantes
        f_out.write(struct.pack(f"<{len(muestras_mono)}h", *muestras_mono))


def mono2estereo(ficIzq, ficDer, ficEste):
    """
    Combina dos archivos monofónicos de 16 bits para construir uno estéreo de 16 bits.
    """
    with open(ficIzq, "rb") as f_izq, open(ficDer, "rb") as f_der, open(
        ficEste, "wb"
    ) as f_out:
        cab_izq = leer_cabecera(f_izq)
        cab_der = leer_cabecera(f_der)

        if cab_izq["NumChannels"] != 1 or cab_der["NumChannels"] != 1:
            raise ValueError("Los archivos de entrada deben ser ambos monofónicos.")
        if cab_izq["SampleRate"] != cab_der["SampleRate"]:
            raise ValueError(
                "La frecuencia de muestreo de ambos ficheros debe coincidir."
            )

        # Leer muestras
        raw_izq = f_izq.read(cab_izq["Subchunk2Size"])
        raw_der = f_der.read(cab_der["Subchunk2Size"])

        m_izq = struct.unpack(f"<{len(raw_izq) // 2}h", raw_izq)
        m_der = struct.unpack(f"<{len(raw_der) // 2}h", raw_der)

        # Asegurar longitud idéntica acortando al menor si difieren ligeramente
        min_len = min(len(m_izq), len(m_der))

        # Entrelazar canales eficientemente sin bucles iterativos explícitos
        muestras_estereo = [
            val for par in zip(m_izq[:min_len], m_der[:min_len]) for val in par
        ]

        # Escribir la cabecera estéreo
        escribir_cabecera(
            f_out,
            num_canales=2,
            sample_rate=cab_izq["SampleRate"],
            bits_per_sample=16,
            num_muestras_canal=min_len,
        )

        f_out.write(struct.pack(f"<{len(muestras_estereo)}h", *muestras_estereo))


def codEstereo(ficEste, ficCod):
    with open(ficEste, "rb") as f_in, open(ficCod, "wb") as f_out:
        cab = leer_cabecera(f_in)
        datos_raw = f_in.read(cab["Subchunk2Size"])
        muestras = struct.unpack(f"<{len(datos_raw) // 2}h", datos_raw)

        ch_izq = muestras[0::2]
        ch_der = muestras[1::2]

        S = [(l + r) // 2 for l, r in zip(ch_izq, ch_der)]
        D = [(l - r) // 2 for l, r in zip(ch_izq, ch_der)]

        # --- LÍNEA CORREGIDA ---
        # 1. Creamos el valor de 32 bits sin signo (pueden salir valores grandes)
        valores_raw = [((s & 0xFFFF) << 16) | (d & 0xFFFF) for s, d in zip(S, D)]
        
        # 2. Forzamos a que Python los interprete en el rango con signo (-2^31 a 2^31 - 1)
        # Si el número supera 2147483647, le restamos 2^32 para que pase a su equivalente negativo.
        muestras_32 = [val if val < 0x80000000 else val - 0x100000000 for val in valores_raw]
        # -----------------------

        escribir_cabecera(
            f_out,
            num_canales=1,
            sample_rate=cab["SampleRate"],
            bits_per_sample=32,
            num_muestras_canal=len(muestras_32),
        )
        f_out.write(struct.pack(f"<{len(muestras_32)}i", *muestras_32))



def decEstereo(ficCod, ficEste):
    """
    Decodifica un archivo de 32 bits de vuelta al formato original estéreo de 16 bits.
    """
    with open(ficCod, "rb") as f_in, open(ficEste, "wb") as f_out:
        cab = leer_cabecera(f_in)

        if cab["NumChannels"] != 1 or cab["BitsPerSample"] != 32:
            raise ValueError(
                "El archivo a decodificar debe ser monofónico de 32 bits."
            )

        datos_raw = f_in.read(cab["Subchunk2Size"])
        muestras_32 = struct.unpack(f"<{len(datos_raw) // 4}i", datos_raw)

        # Extraer semisuma (S) y semidiferencia (D) deshaciendo el desplazamiento de bits
        # Convertimos de vuelta a enteros de 16 bits con signo simulando el desbordamiento binario
        S_raw = [(val >> 16) & 0xFFFF for val in muestras_32]
        D_raw = [val & 0xFFFF for val in muestras_32]

        # Reinterpretar las cadenas de bits a enteros con signo de 16 bits de Python
        S = [struct.unpack("<h", struct.pack("<H", s))[0] for s in S_raw]
        D = [struct.unpack("<h", struct.pack("<H", d))[0] for d in D_raw]

        # Reconstruir canales originales: L = S + D, R = S - D
        ch_izq = [s + d for s, d in zip(S, D)]
        ch_der = [s - d for s, d in zip(S, D)]

        # Entrelazar muestras estéreo
        muestras_estereo = [val for par in zip(ch_izq, ch_der) for val in par]

        # Escribir cabecera estéreo estándar de 16 bits
        escribir_cabecera(
            f_out,
            num_canales=2,
            sample_rate=cab["SampleRate"],
            bits_per_sample=16,
            num_muestras_canal=len(S),
        )

        f_out.write(struct.pack(f"<{len(muestras_estereo)}h", *muestras_estereo))