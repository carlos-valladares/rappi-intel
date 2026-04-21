# Justificación de Zonas — Rappi Competitive Intelligence

Documento que explica los criterios de selección de las 25 zonas de CDMX incluidas en `config/addresses.json` y la lógica estratégica detrás de su distribución.

---

## Objetivo del muestreo geográfico

El sistema necesita capturar cómo varían los precios, costos de envío y tiempos de entrega **según el nivel socioeconómico y la ubicación geográfica** de la zona. La hipótesis central es que las plataformas de delivery no cobran lo mismo en Polanco que en Iztapalapa, y que esa variabilidad es un dato estratégico clave para Rappi.

---

## Criterios de selección

Las zonas fueron elegidas bajo cuatro criterios:

1. **Cobertura socioeconómica** — representar todos los NSE donde Rappi opera, desde A/B hasta C/D.
2. **Cobertura geográfica** — norte, sur, oriente, poniente y centro de la ZMVM.
3. **Densidad de restaurantes** — priorizar zonas con alta presencia de los restaurantes objetivo (McDonald's, Burger King, OXXO, 7-Eleven).
4. **Interés competitivo** — incluir zonas donde la competencia (Uber Eats, DiDi Food) tiene presencia fuerte o donde Rappi tiene oportunidad de ganar mercado.

---

## Distribución por tipo de zona

La distribución es balanceada: **5 zonas por cada tipo**, lo que permite comparaciones directas sin sesgo hacia ningún segmento.

| Tipo de zona | Zonas | NSE representado |
|---|---|---|
| `alto_poder_adquisitivo` | 5 | A/B |
| `clase_media_alta` | 5 | B+/C+ |
| `centro_mixto` | 5 | C/C- (mezcla comercial y residencial) |
| `periferia` | 5 | C/D (zona metropolitana) |
| `sur` | 5 | A/B al D (amplio espectro) |

---

## Justificación por zona

### Tipo: `alto_poder_adquisitivo`

Estas zonas representan el segmento de mayor ticket promedio y mayor penetración de delivery. Son el terreno donde Uber Eats compite más agresivamente.

| Zona | Dirección | Justificación |
|------|-----------|---------------|
| **Polanco** (id 1) | Presidente Masaryk 513 | Zona comercial premium con la mayor densidad de restaurantes de CDMX. Punto de referencia obligado para benchmarking. |
| **Polanco** (id 2) | Av. Ejército Nacional 843 (Antara) | Cubre el corredor corporativo de Polanco — diferente perfil de demanda al punto 1 (oficinas vs. residencial). Dos puntos en Polanco justifican su peso en el mercado. |
| **Lomas** (id 3) | Paseo de las Palmas 735 | Zona residencial NSE A puro. Pocas opciones de restaurante presencial — alta dependencia de delivery. |
| **Santa Fe** (id 4) | Av. Vasco de Quiroga 3800 | Centro corporativo con alta demanda de delivery en horario de almuerzo. Zona con cobertura variable entre plataformas. |
| **Interlomas** (id 5) | Av. Jesús del Monte 41 | Zona residencial premium del Estado de México. Permite medir si las plataformas discriminan precios entre CDMX y EdoMex para el mismo NSE. |

---

### Tipo: `clase_media_alta`

Zonas con alta densidad de restaurantes y usuarios digitalmente activos. Son el volumen principal del negocio de delivery en CDMX.

| Zona | Dirección | Justificación |
|------|-----------|---------------|
| **Roma Norte** (id 6) | Álvaro Obregón 130 | Mayor concentración de restaurantes independientes de CDMX. Zona donde los tres competidores tienen oferta amplia — comparación directa posible. |
| **Condesa** (id 7) | Tamaulipas 202 | Zona gastronómica con perfil de usuario joven y alto uso de apps. Benchmark natural junto con Roma Norte. |
| **Narvarte** (id 8) | Insurgentes Sur 611 | Alta densidad residencial de clase media. Zona de crecimiento de delivery post-pandemia. |
| **Del Valle** (id 9) | Av. División del Norte 1608 | Zona familiar de clase media consolidada. Representa el usuario recurrente de delivery, no el early adopter. |
| **Coyoacán** (id 10) | Francisco Sosa 383 | Zona cultural con perfil de usuario distinto (mayor edad promedio). Permite medir si la penetración de delivery varía con el perfil demográfico. |

---

### Tipo: `centro_mixto`

Zonas de alto tráfico pero con perfil socioeconómico mixto. La cobertura de delivery en estas zonas es inconsistente entre plataformas — lo que las hace estratégicamente relevantes.

| Zona | Dirección | Justificación |
|------|-----------|---------------|
| **Centro Histórico** (id 11) | Madero 73 | Alto tráfico turístico y comercial. Mezcla de demanda local y visitantes. Prueba de cobertura en zona densamente urbanizada. |
| **Doctores** (id 12) | Av. Cuauhtémoc 148 | Zona hospitalaria con demanda de delivery continua (personal médico). NSE C, distinto perfil al Centro. |
| **Tepito** (id 13) | Toltecas 40 | NSE C/D con alta densidad poblacional. Permite medir si las plataformas tienen cobertura real en zonas populares del centro. |
| **Tlatelolco** (id 14) | Manuel González 310 | Unidad habitacional grande — alta concentración de usuarios potenciales en un área pequeña. Caso de uso interesante para delivery en torres de departamentos. |
| **Peralvillo** (id 15) | Circunvalación 10 | Zona popular adyacente al centro. Límite norte de cobertura de las plataformas en la zona centro. |

---

### Tipo: `periferia`

Zonas metropolitanas de alto volumen poblacional pero cobertura de delivery históricamente limitada. Son el mayor campo de batalla de expansión para las tres plataformas.

| Zona | Dirección | Justificación |
|------|-----------|---------------|
| **Iztapalapa Centro** (id 16) | Av. Ermita Iztapalapa 1930 | La alcaldía más poblada de CDMX (~2M habitantes). Cobertura de delivery en crecimiento — dato crítico para estrategia de expansión. |
| **Iztapalapa Sur** (id 17) | Av. Tláhuac 3450 | Zona más alejada del centro dentro de Iztapalapa. Prueba el límite real de cobertura de cada plataforma. |
| **Ecatepec** (id 18) | Av. Central 100 | Municipio más poblado del Estado de México (~1.7M habitantes). Zona dormitorio con alta demanda potencial no atendida. |
| **Chimalhuacán** (id 19) | Av. Bordo de Xochiaca S/N | Periferia lejana oriente. Zona donde la cobertura es mínima o nula — permite documentar los límites de servicio. |
| **Nezahualcóyotl** (id 20) | Av. Texcoco 103 | Zona metropolitana densa con creciente adopción digital. Punto intermedio entre periferia sin cobertura y zona servida. |

---

### Tipo: `sur`

El sur de CDMX tiene un espectro socioeconómico muy amplio — desde Pedregal (NSE A) hasta Tláhuac (NSE D). Esto permite analizar la variabilidad de precios dentro de una misma orientación geográfica.

| Zona | Dirección | Justificación |
|------|-----------|---------------|
| **Tlalpan** (id 21) | Calzada de Tlalpan 4868 (Villa Coapa) | Tlalpan norte, cerca de Perisur. NSE C+/B-. Zona con crecimiento comercial acelerado. |
| **Xochimilco** (id 22) | Guadalupe I. Ramírez 12 | Zona periférica sur con baja cobertura de delivery. Caso límite similar a Chimalhuacán pero dentro de CDMX. |
| **Pedregal** (id 23) | Periférico Sur 3720 | Jardines del Pedregal, NSE A/B. El equivalente al sur de lo que Lomas es al poniente. |
| **Contreras** (id 24) | Camino a Santa Teresa 1000 | Zona residencial sur-poniente con cobertura irregular. Permite detectar zonas desatendidas dentro del NSE B. |
| **Tláhuac** (id 25) | Av. Tláhuac 5800 | Periferia sur-oriente, NSE C/D. La zona con menor cobertura esperada de todo el muestreo — documentar si alguna plataforma llega aquí. |

---

## Zonas notablemente ausentes

Las siguientes zonas relevantes no están incluidas en la versión actual y podrían considerarse para una expansión del muestreo:

| Zona | Razón de exclusión actual | Caso para incluirla |
|------|---------------------------|---------------------|
| Satélite / Naucalpan | Ya hay cobertura EdoMex con Interlomas y Ecatepec | NSE B/C del norte metropolitano |
| Insurgentes Sur (Mixcoac/Acacias) | Cubierto parcialmente por Narvarte | Corredor de alta demanda de delivery |
| Aeropuerto / Venustiano Carranza | Sin presencia de restaurantes objetivo claros | Zona industrial con demanda de oficinas |
| Cuautitlán / Tultitlán | Demasiado alejado del radio de cobertura actual | Límite norte extremo de la ZMVM |

---

## Conclusión

Las 25 zonas cubren un espectro representativo de la ZMVM en términos de NSE, geografía y perfil de cobertura de delivery. La distribución balanceada (5 zonas por tipo) permite hacer comparaciones estadísticas válidas entre segmentos. Las zonas de periferia y sur son especialmente valiosas porque documentan los límites reales de cobertura de cada plataforma, dato que no se obtiene del análisis de zonas premium únicamente.
