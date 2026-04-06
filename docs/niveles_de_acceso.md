# Niveles de Acceso — Casos de Uso del Sistema

El sistema opera en tres niveles de acceso que determinan qué datos están disponibles.
Cada nivel adiciona información que el anterior no puede obtener.

---

## Nivel 1 — Sin Login (Sesión Guest)

**Comando:**
```bash
python main.py
```

**Cómo funciona:** El browser obtiene automáticamente un token guest de cada plataforma.
No se requiere ninguna credencial.

### Datos disponibles

| Campo | Rappi | Uber Eats | DiDi Food |
|-------|-------|-----------|-----------|
| `nombre_restaurante` | ✅ | ✅ | ✅ |
| `calificacion` | ✅ | ✅ | ✅ |
| `tiempo_entrega_min/max` | ✅ | ✅ | ❌ (app only) |
| `descuento_activo` | ✅ | ✅ | ❌ |
| `precio_producto` | ✅ | ✅ | ❌ (app only) |
| `costo_envio` | ✅* | ✅* | ❌ (app only) |
| `costo_servicio` | ⚠️ 0 | ⚠️ null | ❌ (app only) |

**Notas sobre valores en cero o null:**

- **`costo_envio = $0` (Rappi):** Promo "Envío gratis en tu primera orden" aplicada
  automáticamente a tokens guest. Confirmado por el campo `global_offers.tags[].title`
  = `"Envio gratis en tu primera orden"` en la API (código interno: `MX_ONB_FO_NOCASH_FS_V1`).

- **`costo_envio = MXN$0` (Uber Eats):** Promo para nuevos usuarios. Confirmado por
  el texto `"MXN0 delivery fee | new customers"` en el HTML de la página de tienda.

- **`costo_servicio = 0` (Rappi):** El backend retorna `percentage_service_fee: 0.0`
  para sesiones guest. **No es una promo** — no tiene marcador de "primera orden".
  Es una restricción de autenticación: `metadata.service_fee: null`,
  `charges.service.show_fee: False` sin etiqueta de promo asociada.

- **`costo_servicio = null` (Uber Eats):** `fareInfo.serviceFeeCents: null` para
  sesiones guest. **No es una promo** — sin marcador de "new customers". Restricción
  de autenticación confirmada por la feature flag `show_fares_and_total_in_cart: False`
  en el bootstrap de la app.

---

## Nivel 2 — Login Usuario Nuevo

**Comando:**
```bash
python main.py --rappi-email nuevo@email.com --rappi-password pass \
               --ubereats-email nuevo@email.com --ubereats-password pass
```

**Cómo funciona:** El sistema usa las credenciales para autenticarse. Si la cuenta es
nueva, las promos de primera orden seguirán activas.

### Diferencias respecto al Nivel 1

| Campo | Diferencia |
|-------|-----------|
| `costo_envio` | Puede seguir en $0 si aplica promo de primera orden |
| `costo_servicio` | **Ahora disponible** — valor real del cargo por servicio |
| Precios de productos | Pueden variar si hay precios personalizados por usuario |

**Promos de primera orden confirmadas (fuentes verificadas):**

| Plataforma | Tipo de promo | Condición | Fuente |
|---|---|---|---|
| **Rappi** | Envío gratis en hasta 30 órdenes | Tope $20 MXN/envío, primeros 30 días | [promos.rappi.com/mexico/eg30-2025](http://promos.rappi.com/mexico/eg30-2025) |
| **Uber Eats** | $100 MXN descuento en 1er pedido | Mínimo $200 MXN, código mensual | [ubereats.com/promo](https://www.ubereats.com/promo) |
| **DiDi Food** | Hasta $140 MXN descuento | Mínimo $190 MXN, código variable | Reportado en app; sin página oficial pública |

> **Nota sobre Uber Eats:** La promo NO es "envío gratis" — es un descuento de $100 MXN
> sobre el subtotal. El texto `"MXN0 delivery fee | new customers"` en la web refleja
> una promo separada de tarifa de entrega para cuentas nuevas, no el cupón de $100.

> **Nota sobre DiDi Food:** No tiene página oficial de términos de promo accesible.
> Los $140 MXN reportados son de sitios de cupones de terceros. Verificar en la app
> al momento del registro.

> **Nota:** Los niveles premium (Rappi Prime, Uber One, DiDi Plus) están fuera del
> alcance de este sistema. Ver sección "Trabajo Futuro".

---

## Nivel 3 — Login Usuario Normal (Sin Suscripción Premium)

**Comando:**
```bash
python main.py --rappi-email usuario@email.com --rappi-password pass \
               --ubereats-email usuario@email.com --ubereats-password pass \
               --didifood-email usuario@email.com --didifood-password pass
```

**Cómo funciona:** Usuario autenticado sin promos de primera orden activas.
Representa el **caso de uso más valioso** para inteligencia competitiva: datos reales
que pagan los usuarios recurrentes.

### Datos disponibles (completos)

| Campo | Rappi | Uber Eats | DiDi Food |
|-------|-------|-----------|-----------|
| `nombre_restaurante` | ✅ | ✅ | ✅ |
| `calificacion` | ✅ | ✅ | ✅ |
| `tiempo_entrega_min/max` | ✅ | ✅ | ⚠️ pendiente |
| `descuento_activo` | ✅ | ✅ | ⚠️ pendiente |
| `precio_producto` | ✅ | ✅ | ⚠️ pendiente |
| `costo_envio` | ✅ real | ✅ real | ⚠️ pendiente |
| `costo_servicio` | ✅ real | ✅ real | ⚠️ pendiente |

### Estado de implementación del login

| Plataforma | Tipo de Login | Estado |
|---|---|---|
| **Rappi** | API directa (`POST /api/rocket/v2/login`) | 🔧 Pendiente implementar |
| **Uber Eats** | Browser (formulario web) | 🔧 Pendiente implementar |
| **DiDi Food** | Browser / app móvil | ⛔ No viable vía web (ver DT-04) |

> El scaffolding de credenciales está completo en las tres plataformas. Los parámetros
> CLI (`--rappi-email`, `--ubereats-email`, etc.) reciben y pasan las credenciales al
> scraper en `self.credenciales`. La lógica de autenticación (llamada al endpoint de
> login y uso del token resultante) está pendiente de implementar para Rappi y Uber Eats.

---

## Trabajo Futuro — Nivel Premium

Los siguientes niveles de suscripción quedan fuera del alcance actual:

| Suscripción | Plataforma | Beneficios adicionales |
|---|---|---|
| **Rappi Prime** | Rappi | Envío gratis ilimitado, sin costo de servicio |
| **Uber One** | Uber Eats | Envío gratis, descuentos exclusivos |
| **DiDi Plus** | DiDi Food | Envío gratis, prioridad de entrega |

Para implementar estos niveles se requeriría una cuenta con suscripción activa y
mapear los campos adicionales que la API retorna para usuarios premium.
