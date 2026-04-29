# -*- coding: utf-8 -*-
"""
generar_portal_servidor.py  —  AABN v3
Corre EN EL SERVIDOR del club.
Fuente: Socios + Socios Servicios + Servicios + Transacciones (AABN_d.accdb)
No usa A_Padron (descartado: duplicados masivos, numeracion incompatible).
"""

import os, re, sys, json, logging, subprocess
from datetime import date, datetime

# ══════════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════════
ACCDB_PATH = r'C:\Siwin\AABN\AABN_d.accdb'
REPO_DIR   = r'C:\AABN\aabn-sitio'
HTML_FILE  = os.path.join(REPO_DIR, 'panel-admin.html')
LOG_FILE   = r'C:\AABN\portal_servidor.log'
# ══════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    filename=LOG_FILE, level=logging.INFO,
    format='%(asctime)s  %(levelname)s  %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger()
log.addHandler(logging.StreamHandler(sys.stdout))
step = log.info


# ── Disciplina desde nombre de servicio ───────────────────────────────────
def _disc_de_servicio(nombre_srv):
    n = (nombre_srv or '').lower()
    if 'futbol' in n or 'fútbol' in n or 'carnet' in n:         return 'FUTBOL'
    if 'basquet' in n or 'básquet' in n or 'basket' in n:       return 'BASQUET'
    if 'gimn' in n or 'telas' in n or 'acrobac' in n or 'circo' in n: return 'GIMNASIA'
    if 'patin' in n or 'patín' in n:                            return 'PATIN'
    if 'tenis' in n:                                            return 'TENIS'
    return None

def _nro_socio_de(cod_aabn, id_socio):
    """Extrae numero familiar de CodAABN ('05583-03' -> 5583)."""
    if cod_aabn:
        try:
            return int(str(cod_aabn).split('-')[0])
        except Exception:
            pass
    return _int(id_socio)

def _norm_dni(v):
    if not v: return ''
    if isinstance(v, float): v = int(v)
    return re.sub(r'[.\s\-]', '', str(v)).strip()

def _fmt_fecha(v):
    if not v: return ''
    try:
        if hasattr(v, 'strftime'):
            return v.strftime('%d/%m/%Y')
        return str(v)[:10]
    except Exception:
        return ''

def _float(v):
    try: return round(float(v or 0), 2)
    except Exception: return 0.0

def _int(v):
    try: return int(v or 0)
    except Exception: return 0


# ── Conexión ──────────────────────────────────────────────────────────────
def abrir_conn():
    import win32com.client
    conn = win32com.client.Dispatch('ADODB.Connection')
    conn.Open(f'Provider=Microsoft.ACE.OLEDB.12.0;Data Source={ACCDB_PATH};')
    return conn


# ── Lectura de tablas ─────────────────────────────────────────────────────

def leer_socios(conn):
    """Devuelve lista de dicts con todos los campos relevantes de Socios."""
    step('  Leyendo Socios...')
    sql = ('SELECT IdSocio, Número, Nombre, Domicilio, Localidad, Telefono, '
           '[E-Mail], FechaIng, Documento, Activo, Estado, [DebAutomático], CBU, CodAABN '
           'FROM Socios')
    rs = conn.Execute(sql)[0]
    result = []
    while not rs.EOF:
        def fv(name):
            try: return rs.Fields(name).Value
            except Exception: return None
        result.append({
            'id_socio':  fv('IdSocio'),
            'nombre':    str(fv('Nombre') or '').strip(),
            'dni':       _norm_dni(fv('Documento')),
            'domicilio': str(fv('Domicilio') or '').strip(),
            'telefono':  str(fv('Telefono') or '').strip(),
            'email':     str(fv('E-Mail') or '').strip(),
            'fecha_ing': _fmt_fecha(fv('FechaIng')),
            'estado':    str(fv('Estado') or '').strip(),
            'deb_auto':  bool(fv('DebAutomático')),
            'cbu':       str(fv('CBU') or '').strip(),
            'cod_aabn':  str(fv('CodAABN') or '').strip(),
            'nro_socio': _nro_socio_de(fv('CodAABN'), fv('IdSocio')),
        })
        rs.MoveNext()
    rs.Close()
    step(f'  {len(result)} socios en Socios')
    return result


def leer_disciplinas(conn):
    """Devuelve dict {id_socio: disciplina} leyendo Socios Servicios + Servicios."""
    step('  Leyendo Servicios...')
    rs = conn.Execute('SELECT IdServ, Servicio FROM Servicios')[0]
    srv_disc = {}
    while not rs.EOF:
        id_srv = rs.Fields('IdServ').Value
        nombre = str(rs.Fields('Servicio').Value or '').strip()
        disc   = _disc_de_servicio(nombre)
        if disc and id_srv is not None:
            srv_disc[_int(id_srv)] = disc
        rs.MoveNext()
    rs.Close()
    step(f'  {len(srv_disc)} servicios con disciplina identificada')

    step('  Leyendo Socios Servicios...')
    rs = conn.Execute('SELECT IdSocio, IdServicio FROM [Socios Servicios]')[0]
    disc_result = {}
    con_servicio = set()
    while not rs.EOF:
        id_s   = rs.Fields('IdSocio').Value
        id_srv = rs.Fields('IdServicio').Value
        if id_s is not None:
            con_servicio.add(_int(id_s))
            if id_srv is not None:
                disc = srv_disc.get(_int(id_srv))
                if disc and _int(id_s) not in disc_result:
                    disc_result[_int(id_s)] = disc
        rs.MoveNext()
    rs.Close()
    step(f'  {len(con_servicio)} socios con servicio, {len(disc_result)} con disciplina identificada')
    return disc_result, con_servicio


def leer_deuda_pendiente(conn):
    """Devuelve dict keyed por IdSocio con cant_pendientes y deuda_total."""
    step('  Leyendo Pendientes...')
    try:
        sql = ('SELECT t.IdSocio, COUNT(*) AS cant, SUM(p.Importe) AS total '
               'FROM Pendientes AS p '
               'INNER JOIN Transacciones AS t ON p.[Transacción] = t.Id '
               'WHERE t.IdSocio IS NOT NULL '
               'GROUP BY t.IdSocio')
        rs = conn.Execute(sql)[0]
        result = {}
        while not rs.EOF:
            id_s = rs.Fields('IdSocio').Value
            if id_s is not None:
                result[_int(id_s)] = {
                    'cant_pendientes': _int(rs.Fields('cant').Value),
                    'deuda_total':     _float(rs.Fields('total').Value),
                }
            rs.MoveNext()
        rs.Close()
        step(f'  {len(result)} socios con deuda en Pendientes')
        return result
    except Exception as e:
        step(f'  [WARN] leer_deuda_pendiente: {e}')
        return {}


def leer_pagos(conn):
    """Devuelve dict keyed por IdSocio con ultimo_pago y cobrado_2026."""
    step('  Leyendo Transacciones (cobros)...')
    try:
        sql = ('SELECT IdSocio, MAX(FechaCobro) AS ultimo_pago, '
               'SUM(IIF(FechaCobro>=#2026-01-01# AND FechaCobro<#2027-01-01#, Importe, 0)) AS cobrado_2026 '
               'FROM Transacciones '
               'WHERE Tipo = "CPN" AND Cpr = "CTS" '
               'AND FechaCobro IS NOT NULL AND IdSocio IS NOT NULL '
               'GROUP BY IdSocio')
        rs = conn.Execute(sql)[0]
        result = {}
        while not rs.EOF:
            id_s = rs.Fields('IdSocio').Value
            if id_s is not None:
                result[_int(id_s)] = {
                    'ultimo_pago':  _fmt_fecha(rs.Fields('ultimo_pago').Value),
                    'cobrado_2026': _float(rs.Fields('cobrado_2026').Value),
                }
            rs.MoveNext()
        rs.Close()
        step(f'  {len(result)} socios con historial de pagos')
        return result
    except Exception as e:
        step(f'  [WARN] leer_pagos: {e}')
        return {}


# ── Construcción de datos ─────────────────────────────────────────────────

def construir_data(socios_list, disc_por_socio, socios_con_servicio, deuda, pagos):
    filas, disc_set = [], set()
    conteo = {'al_dia': 0, 'deudor': 0, 'baja': 0}

    for s in socios_list:
        id_socio = _int(s['id_socio']) if s['id_socio'] is not None else None

        d = deuda.get(id_socio, {}) if id_socio else {}
        p = pagos.get(id_socio, {}) if id_socio else {}

        cant_pend  = d.get('cant_pendientes', 0)
        deuda_real = d.get('deuda_total', 0)
        tiene_servicio = id_socio in socios_con_servicio if id_socio else False
        tiene_deuda    = cant_pend > 0 or deuda_real > 0

        disc = disc_por_socio.get(id_socio) if id_socio else None
        if disc:
            disc_set.add(disc)

        if tiene_deuda:
            estado_final = 'deudor'; conteo['deudor'] += 1
        elif tiene_servicio:
            estado_final = 'al_dia'; conteo['al_dia'] += 1
        else:
            estado_final = 'baja';   conteo['baja']   += 1

        filas.append({
            'nro_socio':    s['nro_socio'],
            'nombre':       s['nombre'],
            'dni':          s['dni'],
            'domicilio':    s['domicilio'],
            'telefono':     s['telefono'],
            'email':        s['email'],
            'fecha_ing':    s['fecha_ing'],
            'deb_auto':     s['deb_auto'],
            'estado_padron':s['estado'],
            'estado_final': estado_final,
            'disciplinas':  disc or '',
            'cant_pend':    cant_pend,
            'deuda_total':  deuda_real,
            'ultimo_pago':  p.get('ultimo_pago', ''),
            'cobrado_2026': p.get('cobrado_2026', 0),
        })

    return {
        '_filas':       filas,
        '_conteo':      conteo,
        '_total':       len(filas),
        '_disciplinas': sorted(disc_set),
        '_generado':    date.today().strftime('%d/%m/%Y'),
    }


# ── Template HTML ─────────────────────────────────────────────────────────
HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Dashboard Socios — A.A.B.N</title>
  <script src="https://cdn.tailwindcss.com"><\/script>
  <script>
    tailwind.config = {
      theme: {
        extend: {
          colors: {
            verde:{50:"#f0f9f3",100:"#d9f0e1",200:"#b2e0c3",300:"#7cc99a",
                   400:"#46ad6f",500:"#28904f",600:"#1c743e",700:"#195e34",
                   800:"#174b2b",900:"#133d23"}
          },
          fontFamily: {
            sans:   ["Rag","Segoe UI","Arial","sans-serif"],
            expose: ["Expose","Arial Black","sans-serif"],
          }
        }
      }
    }
  <\/script>
  <style>
    @font-face{font-family:"Expose";src:url("fonts/Expose-Black.woff2") format("woff2");font-weight:900;}
    @font-face{font-family:"Expose";src:url("fonts/Expose-Bold.woff2") format("woff2");font-weight:700;}
    @font-face{font-family:"Expose";src:url("fonts/Expose-Regular.woff2") format("woff2");font-weight:400;}
    @font-face{font-family:"Rag";src:url("fonts/Rag-Regular.woff2") format("woff2"),url("fonts/Rag-Regular.woff") format("woff");font-weight:400;font-style:normal;}
    @font-face{font-family:"Rag";src:url("fonts/Rag-Bold.woff2") format("woff2"),url("fonts/Rag-Bold.woff") format("woff");font-weight:700;font-style:normal;}
    @font-face{font-family:"Rag";src:url("fonts/Rag-Black.woff2") format("woff2"),url("fonts/Rag-Black.woff") format("woff");font-weight:900;font-style:normal;}
    *{box-sizing:border-box;}
    html,body{height:100%;margin:0;}
    body{background:#0d1117;}

    .badge-al_dia{background:rgba(16,185,129,.1);color:#6ee7b7;border:1px solid rgba(110,231,183,.15);}
    .badge-deudor{background:rgba(239,68,68,.1);color:#fca5a5;border:1px solid rgba(252,165,165,.15);}
    .badge-baja  {background:rgba(255,255,255,.05);color:rgba(255,255,255,.22);border:1px solid rgba(255,255,255,.08);}

    tr.data-row:hover td{background:rgba(255,255,255,.03);}
    tr.data-row:nth-child(even) td{background:rgba(0,0,0,.13);}
    tr.data-row td{transition:background .1s;}
    tr.data-row{border-bottom:1px solid rgba(255,255,255,.04);}

    .sortable{cursor:pointer;user-select:none;transition:color .15s;}
    .sortable:hover{color:rgba(255,255,255,.65)!important;}
    thead th{position:sticky;top:0;z-index:10;}

    .table-wrap{max-height:calc(100vh - 300px);overflow:auto;scrollbar-width:thin;scrollbar-color:rgba(255,255,255,.08) transparent;}
    .table-wrap::-webkit-scrollbar{width:5px;height:5px;}
    .table-wrap::-webkit-scrollbar-track{background:transparent;}
    .table-wrap::-webkit-scrollbar-thumb{background:rgba(255,255,255,.1);border-radius:10px;}

    .input-f{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:10px;
             padding:7px 13px;font-size:12px;color:rgba(255,255,255,.65);outline:none;
             transition:border-color .2s,box-shadow .2s;font-family:inherit;}
    .input-f:focus{border-color:rgba(40,144,79,.45);box-shadow:0 0 0 3px rgba(40,144,79,.07);}
    .input-f::placeholder{color:rgba(255,255,255,.2);}
    .input-f option{background:#111520;color:#d1d5db;}

    .tag-disc{display:inline-flex;align-items:center;background:rgba(40,144,79,.13);color:#86efac;
              font-size:10px;font-weight:600;padding:1px 7px;border-radius:20px;
              white-space:nowrap;border:1px solid rgba(134,239,172,.14);}
    .tag-deb{display:inline-flex;align-items:center;background:rgba(59,130,246,.12);color:#93c5fd;
             font-size:10px;font-weight:700;padding:1px 6px;border-radius:8px;border:1px solid rgba(147,197,253,.15);}

    .card-num{font-size:2.4rem;font-weight:900;line-height:1;letter-spacing:-1.5px;}
    .card-num-sm{font-size:1.6rem;font-weight:900;line-height:1;letter-spacing:-1px;}

    .nav-item{color:rgba(255,255,255,.28);display:flex;align-items:center;gap:10px;
              padding:9px 12px;border-radius:12px;font-size:13px;transition:all .15s;
              text-decoration:none;border:1px solid transparent;cursor:pointer;background:transparent;
              width:100%;text-align:left;font-family:inherit;}
    .nav-item:hover{color:rgba(255,255,255,.6);background:rgba(255,255,255,.04);}
    .nav-active{background:rgba(28,116,62,.22)!important;border-color:rgba(28,116,62,.28)!important;color:#86efac!important;}

    td,th{white-space:nowrap;}
  <\/style>
<\/head>
<body class="font-sans antialiased">

<div style="display:flex;height:100vh;overflow:hidden;">

<!-- ── SIDEBAR ── -->
<aside style="width:220px;flex-shrink:0;background:#080b10;border-right:1px solid rgba(255,255,255,.05);display:flex;flex-direction:column;z-index:40;">

  <div style="padding:20px;border-bottom:1px solid rgba(255,255,255,.05);flex-shrink:0">
    <a href="index.html" style="display:flex;align-items:center;gap:12px;text-decoration:none">
      <img src="images.jpeg" alt="AABN" style="height:32px;width:auto;border-radius:8px;opacity:.88">
      <div>
        <div class="font-expose font-black text-sm tracking-widest uppercase" style="color:#fff;line-height:1">A.A.B.N</div>
        <div style="font-size:9px;letter-spacing:.1em;margin-top:2px;color:rgba(255,255,255,.18)">Banda Norte</div>
      </div>
    </a>
  </div>

  <nav style="flex:1;padding:12px;overflow-y:auto;display:flex;flex-direction:column;gap:2px">
    <div style="font-size:9px;font-weight:700;letter-spacing:.15em;text-transform:uppercase;padding:0 8px;margin-bottom:8px;color:rgba(255,255,255,.18)">Gestión</div>
    <a href="#" class="nav-item nav-active">
      <svg style="width:16px;height:16px;flex-shrink:0" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2M9 7a4 4 0 100 8 4 4 0 000-8zM23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75"/>
      </svg>
      Socios
    </a>
    <a href="estado-resultados.html" class="nav-item">
      <svg style="width:16px;height:16px;flex-shrink:0" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/>
      </svg>
      Finanzas
    </a>

    <div style="height:1px;background:rgba(255,255,255,.05);margin:8px 0"></div>
    <div style="font-size:9px;font-weight:700;letter-spacing:.15em;text-transform:uppercase;padding:0 8px;margin-bottom:8px;color:rgba(255,255,255,.18)">Navegación</div>
    <a href="selector.html" class="nav-item">
      <svg style="width:16px;height:16px;flex-shrink:0" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" d="M4 6h16M4 12h16M4 18h7"/>
      </svg>
      Panel principal
    </a>
    <a href="index.html" class="nav-item">
      <svg style="width:16px;height:16px;flex-shrink:0" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"/>
      </svg>
      Sitio web
    </a>
  </nav>

  <div style="padding:12px;border-top:1px solid rgba(255,255,255,.05);flex-shrink:0">
    <div id="admin-info" style="display:none;align-items:center;gap:10px;padding:6px 8px;margin-bottom:4px;border-radius:12px">
      <div style="width:28px;height:28px;border-radius:50%;background:rgba(28,116,62,.35);display:flex;align-items:center;justify-content:center;flex-shrink:0">
        <svg style="width:14px;height:14px;color:#86efac" fill="currentColor" viewBox="0 0 20 20">
          <path fill-rule="evenodd" d="M10 9a3 3 0 100-6 3 3 0 000 6zm-7 9a7 7 0 1114 0H3z" clip-rule="evenodd"/>
        </svg>
      </div>
      <div style="min-width:0">
        <div id="admin-nombre" style="font-size:12px;font-weight:600;color:rgba(255,255,255,.75);overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></div>
        <div id="admin-rol" style="font-size:10px;color:rgba(255,255,255,.22);overflow:hidden;text-overflow:ellipsis;white-space:nowrap"></div>
      </div>
    </div>
    <button onclick="cerrarSesion()" class="nav-item">
      <svg style="width:16px;height:16px;flex-shrink:0" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1"/>
      </svg>
      Cerrar sesión
    </button>
  </div>
</aside>

<!-- ── MAIN ── -->
<div style="flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0">

  <header style="flex-shrink:0;height:56px;display:flex;align-items:center;justify-content:space-between;padding:0 32px;border-bottom:1px solid rgba(255,255,255,.05);background:rgba(13,17,23,.9);backdrop-filter:blur(12px);z-index:30">
    <div style="display:flex;align-items:center;gap:12px">
      <h1 class="font-expose font-black" style="font-size:15px;color:#fff;letter-spacing:-.01em">Dashboard Socios</h1>
      <span style="font-size:12px;color:rgba(255,255,255,.14)">Asociación Atlética Banda Norte</span>
    </div>
    <div style="font-size:12px;color:rgba(255,255,255,.25)">
      Actualizado: <span id="fecha-gen" style="font-weight:600;color:rgba(255,255,255,.5);margin-left:4px"></span>
    </div>
  </header>

  <div style="flex:1;overflow-y:auto;padding:28px 32px">

    <!-- STAT CARDS -->
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:24px">

      <div style="background:#0e1117;border:1px solid rgba(255,255,255,.06);border-radius:16px;padding:20px">
        <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:rgba(255,255,255,.25);margin-bottom:14px">Padrón total</div>
        <div id="c-total" class="card-num" style="color:#fff"></div>
        <div style="font-size:11px;color:rgba(255,255,255,.14);margin-top:10px">socios en BD</div>
      </div>

      <div style="background:#0e1117;border:1px solid rgba(28,116,62,.35);border-radius:16px;padding:20px;position:relative;overflow:hidden">
        <div style="position:absolute;top:16px;right:16px;width:6px;height:6px;border-radius:50%;background:#28904f"></div>
        <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:rgba(134,239,172,.5);margin-bottom:14px">Al día</div>
        <div id="c-aldia" class="card-num" style="color:#86efac"></div>
        <div id="p-aldia" style="font-size:11px;color:rgba(134,239,172,.25);margin-top:10px"></div>
      </div>

      <div style="background:#0e1117;border:1px solid rgba(185,28,28,.25);border-radius:16px;padding:20px;position:relative;overflow:hidden">
        <div style="position:absolute;top:16px;right:16px;width:6px;height:6px;border-radius:50%;background:#ef4444"></div>
        <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:rgba(252,165,165,.5);margin-bottom:14px">Deudores</div>
        <div id="c-deudor" class="card-num" style="color:#fca5a5"></div>
        <div id="p-deudor" style="font-size:11px;color:rgba(252,165,165,.22);margin-top:10px"></div>
      </div>

      <div style="background:#0e1117;border:1px solid rgba(251,146,60,.2);border-radius:16px;padding:20px;position:relative;overflow:hidden">
        <div style="position:absolute;top:16px;right:16px;width:6px;height:6px;border-radius:50%;background:#f97316"></div>
        <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:rgba(251,146,60,.5);margin-bottom:14px">Deuda total</div>
        <div id="c-deuda" class="card-num-sm" style="color:#fdba74"></div>
        <div id="p-cobrado" style="font-size:11px;color:rgba(251,146,60,.3);margin-top:10px"></div>
      </div>

    </div>

    <!-- TABLE CARD -->
    <div style="background:#0e1117;border:1px solid rgba(255,255,255,.06);border-radius:16px;overflow:hidden">

      <div style="padding:20px 24px;border-bottom:1px solid rgba(255,255,255,.05)">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px">
          <div>
            <h2 class="font-expose font-bold" style="font-size:15px;color:#fff;letter-spacing:-.01em">Padrón Completo</h2>
            <p style="font-size:11px;color:rgba(255,255,255,.2);margin-top:2px">Click en columna para ordenar · <span id="conteo-f" style="color:rgba(134,239,172,.5)"></span></p>
          </div>
        </div>
        <div style="display:flex;flex-wrap:wrap;gap:8px">
          <input id="f-buscar" oninput="filtrar()" type="text"
            placeholder="Buscar nombre, DNI, Nº, email, teléfono…"
            class="input-f" style="flex:1;min-width:200px">
          <select id="f-estado" onchange="filtrar()" class="input-f">
            <option value="">Todos los estados</option>
            <option value="al_dia">Al día</option>
            <option value="deudor">Deudor</option>
            <option value="baja">Baja</option>
          </select>
          <select id="f-disc" onchange="filtrar()" class="input-f">
            <option value="">Todas las disciplinas</option>
            <option value="__sin__">Sin disciplina</option>
          </select>
          <select id="f-deb" onchange="filtrar()" class="input-f">
            <option value="">Débito: todos</option>
            <option value="1">Con débito</option>
            <option value="0">Sin débito</option>
          </select>
          <button onclick="limpiar()" class="input-f" style="cursor:pointer;padding:7px 16px;color:rgba(255,255,255,.35)">
            Limpiar
          </button>
        </div>
      </div>

      <div class="table-wrap">
        <table style="width:100%;font-size:13px;border-collapse:collapse">
          <thead>
            <tr style="border-bottom:1px solid rgba(255,255,255,.05);background:#080b10">
              <th class="sortable px-3 py-3 text-center" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(255,255,255,.22)" onclick="ordenar('nro_socio')"># ↕</th>
              <th class="sortable px-4 py-3 text-left" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(255,255,255,.22)" onclick="ordenar('nombre')">Nombre ↕</th>
              <th class="sortable px-4 py-3 text-left" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(255,255,255,.22)" onclick="ordenar('dni')">DNI ↕</th>
              <th class="px-4 py-3 text-left" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(255,255,255,.22)">Teléfono</th>
              <th class="px-4 py-3 text-left" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(255,255,255,.22)">Email</th>
              <th class="px-4 py-3 text-center" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(255,255,255,.22)">Estado</th>
              <th class="px-4 py-3 text-left" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(255,255,255,.22)">Disciplina</th>
              <th class="sortable px-4 py-3 text-center" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(255,255,255,.22)" onclick="ordenar('cant_pend')">Cuotas ↕</th>
              <th class="sortable px-4 py-3 text-right" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(255,255,255,.22)" onclick="ordenar('deuda_total')">Deuda ↕</th>
              <th class="sortable px-4 py-3 text-left" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(255,255,255,.22)" onclick="ordenar('ultimo_pago')">Últ. pago ↕</th>
              <th class="sortable px-4 py-3 text-right" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(255,255,255,.22)" onclick="ordenar('cobrado_2026')">Cobrado 2026 ↕</th>
              <th class="px-4 py-3 text-center" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(255,255,255,.22)">Déb.</th>
            </tr>
          </thead>
          <tbody id="tbody"></tbody>
        </table>
      </div>

      <div style="padding:12px 24px;border-top:1px solid rgba(255,255,255,.05);display:flex;justify-content:space-between;font-size:11px;color:rgba(255,255,255,.14)">
        <span>Fuente: AABN_d.accdb · Siwin</span>
        <span>Generado: <span id="fecha-pie" style="font-weight:600;color:rgba(255,255,255,.3)"></span></span>
      </div>

    </div>
  </div>
</div>

</div>

<script>
const DATA = PLACEHOLDER_DATA;

const filasTodas = DATA._filas;
let filasFiltradas = [...filasTodas];
let ordenCol = "nombre", ordenAsc = true;

// Auth
const admin = JSON.parse(sessionStorage.getItem("admin") || "null");
if (!admin) { window.location.href = "login.html"; }
else {
  const ai = document.getElementById("admin-info"); ai.style.display = "flex";
  document.getElementById("admin-nombre").textContent = admin.nombre;
  document.getElementById("admin-rol").textContent    = admin.rol;
}
function cerrarSesion() { sessionStorage.removeItem("admin"); window.location.href = "login.html"; }

// Fechas
const gen = DATA._generado || "";
document.getElementById("fecha-gen").textContent = gen;
document.getElementById("fecha-pie").textContent = gen;

// Tarjetas
const c   = DATA._conteo;
const tot = DATA._total;
const deudaTotal  = filasTodas.reduce((s, r) => s + (r.deuda_total  || 0), 0);
const cobrado2026 = filasTodas.reduce((s, r) => s + (r.cobrado_2026 || 0), 0);

document.getElementById("c-total").textContent   = tot.toLocaleString("es-AR");
document.getElementById("c-aldia").textContent   = (c.al_dia||0).toLocaleString("es-AR");
document.getElementById("c-deudor").textContent  = (c.deudor||0).toLocaleString("es-AR");
document.getElementById("c-deuda").textContent   = "$" + Math.round(deudaTotal/1000).toLocaleString("es-AR") + "K";
document.getElementById("p-aldia").textContent   = Math.round((c.al_dia||0)*100/tot) + "% del padrón";
document.getElementById("p-deudor").textContent  = Math.round((c.deudor||0)*100/tot) + "% del padrón";
document.getElementById("p-cobrado").textContent = "Cobrado: $" + Math.round(cobrado2026/1000).toLocaleString("es-AR") + "K";

// Select disciplinas
const selDisc = document.getElementById("f-disc");
(DATA._disciplinas || []).forEach(d => {
  const o = document.createElement("option");
  o.value = d; o.textContent = d;
  selDisc.appendChild(o);
});

function filtrar() {
  const q      = document.getElementById("f-buscar").value.toLowerCase().trim();
  const estado = document.getElementById("f-estado").value;
  const disc   = document.getElementById("f-disc").value;
  const deb    = document.getElementById("f-deb").value;

  filasFiltradas = filasTodas.filter(r => {
    if (estado && r.estado_final !== estado) return false;
    if (disc === "__sin__" && r.disciplinas)  return false;
    if (disc && disc !== "__sin__" && r.disciplinas !== disc) return false;
    if (deb === "1" && !r.deb_auto) return false;
    if (deb === "0" &&  r.deb_auto) return false;
    if (q) {
      const nro  = String(r.nro_socio || "");
      const tel  = (r.telefono || "").toLowerCase();
      const mail = (r.email    || "").toLowerCase();
      if (!r.nombre.toLowerCase().includes(q) &&
          !r.dni.includes(q) && !nro.includes(q) &&
          !tel.includes(q)   && !mail.includes(q)) return false;
    }
    return true;
  });
  renderTabla();
}

function limpiar() {
  document.getElementById("f-buscar").value = "";
  document.getElementById("f-estado").value = "";
  document.getElementById("f-disc").value   = "";
  document.getElementById("f-deb").value    = "";
  filasFiltradas = [...filasTodas];
  renderTabla();
}

function ordenar(col) {
  if (ordenCol === col) ordenAsc = !ordenAsc;
  else { ordenCol = col; ordenAsc = true; }
  const numCols = ["nro_socio","cant_pend","deuda_total","cobrado_2026"];
  filasFiltradas.sort((a, b) => {
    let va = a[col], vb = b[col];
    if (numCols.includes(col)) { va = va||0; vb = vb||0; }
    else { va = (va||"").toString().toLowerCase(); vb = (vb||"").toString().toLowerCase(); }
    if (va < vb) return ordenAsc ? -1 : 1;
    if (va > vb) return ordenAsc ?  1 : -1;
    return 0;
  });
  renderTabla();
}

const LABELS = {al_dia:"Al día", deudor:"Deudor", baja:"Baja"};

function renderTabla() {
  const tbody = document.getElementById("tbody");
  const conteoEl = document.getElementById("conteo-f");
  if (conteoEl) conteoEl.textContent = filasFiltradas.length.toLocaleString("es-AR") + " socios";

  if (!filasFiltradas.length) {
    tbody.innerHTML = `<tr><td colspan="12" class="text-center py-16 text-sm" style="color:rgba(255,255,255,.2)">Sin resultados para los filtros aplicados</td></tr>`;
    return;
  }

  tbody.innerHTML = filasFiltradas.map(r => {
    const deudaFmt = (r.deuda_total || 0) > 0
      ? `<span style="font-weight:700;color:#fca5a5">$${Math.round(r.deuda_total).toLocaleString("es-AR")}</span>`
      : `<span style="color:rgba(255,255,255,.1)">—</span>`;
    const cobFmt = (r.cobrado_2026 || 0) > 0
      ? `<span style="font-weight:600;color:#86efac">$${Math.round(r.cobrado_2026).toLocaleString("es-AR")}</span>`
      : `<span style="color:rgba(255,255,255,.1)">—</span>`;
    const discFmt = r.disciplinas
      ? `<span class="tag-disc">${r.disciplinas}</span>`
      : `<span style="color:rgba(255,255,255,.1)">—</span>`;
    const telFmt = r.telefono
      ? `<a href="tel:${r.telefono}" style="color:rgba(100,180,255,.65)">${r.telefono}</a>`
      : `<span style="color:rgba(255,255,255,.1)">—</span>`;
    const mailFmt = r.email
      ? `<a href="mailto:${r.email}" style="color:rgba(100,180,255,.65);font-size:11px">${r.email}</a>`
      : `<span style="color:rgba(255,255,255,.1)">—</span>`;
    const debFmt = r.deb_auto
      ? `<span class="tag-deb">DBT</span>`
      : `<span style="color:rgba(255,255,255,.1)">—</span>`;
    const cantFmt = (r.cant_pend || 0) > 0
      ? `<span style="font-weight:700;color:#fca5a5">${r.cant_pend}</span>`
      : `<span style="color:rgba(255,255,255,.1)">—</span>`;
    const badgeCls = "badge-" + (r.estado_final || "baja");
    return `<tr class="data-row">
      <td class="px-3 py-3 text-center text-xs font-mono" style="color:rgba(255,255,255,.2)">${r.nro_socio||"—"}</td>
      <td class="px-4 py-3 font-semibold" style="color:rgba(255,255,255,.82)">${r.nombre}</td>
      <td class="px-4 py-3 font-mono text-xs" style="color:rgba(255,255,255,.3)">${r.dni||"—"}</td>
      <td class="px-4 py-3 text-xs">${telFmt}</td>
      <td class="px-4 py-3 text-xs">${mailFmt}</td>
      <td class="px-4 py-3 text-center">
        <span class="${badgeCls} text-xs font-bold px-2.5 py-0.5 rounded-full">
          ${LABELS[r.estado_final]||r.estado_final||"—"}
        </span>
      </td>
      <td class="px-4 py-3">${discFmt}</td>
      <td class="px-4 py-3 text-center">${cantFmt}</td>
      <td class="px-4 py-3 text-right">${deudaFmt}</td>
      <td class="px-4 py-3 text-xs" style="color:rgba(255,255,255,.3)">${r.ultimo_pago||"—"}</td>
      <td class="px-4 py-3 text-right">${cobFmt}</td>
      <td class="px-4 py-3 text-center">${debFmt}</td>
    </tr>`;
  }).join("");
}

// Init
ordenar("nombre");
<\/script>
<\/body>
<\/html>
"""


# ── Generación del HTML ───────────────────────────────────────────────────
def generar_html(data):
    data_json = json.dumps(data, ensure_ascii=False, separators=(',', ':'), default=str)
    html = HTML_TEMPLATE.replace('PLACEHOLDER_DATA', data_json)
    os.makedirs(REPO_DIR, exist_ok=True)
    with open(HTML_FILE, 'w', encoding='utf-8') as f:
        f.write(html)
    step(f'  panel-admin.html → {os.path.getsize(HTML_FILE):,} bytes')


# ── Git push ──────────────────────────────────────────────────────────────
def git_push():
    hoy  = date.today().strftime('%d/%m/%Y')
    cmds = [
        ['git', '-C', REPO_DIR, 'add', 'panel-admin.html'],
        ['git', '-C', REPO_DIR, 'commit', '-m', f'Dashboard actualizado {hoy}'],
        ['git', '-C', REPO_DIR, 'push'],
    ]
    for cmd in cmds:
        r = subprocess.run(cmd, capture_output=True, text=True)
        out = (r.stdout + r.stderr).lower()
        if r.returncode != 0:
            if 'nothing to commit' in out:
                step('  git: sin cambios nuevos')
                return
            step(f'  [WARN] {cmd[2]}: {r.stderr.strip()}')
        else:
            step(f'  OK: git {cmd[2]}')


# ── Main ──────────────────────────────────────────────────────────────────
def main():
    inicio = datetime.now()
    step('=' * 60)
    step(f'INICIO: {inicio.strftime("%Y-%m-%d %H:%M:%S")}')
    try:
        conn = abrir_conn()
        step(f'  Conectado a {ACCDB_PATH}')

        step('[1/4] Leyendo socios y disciplinas...')
        socios_list                    = leer_socios(conn)
        disc_por_socio, socios_con_srv = leer_disciplinas(conn)

        step('[2/4] Leyendo deuda pendiente...')
        deuda = leer_deuda_pendiente(conn)

        step('[3/4] Leyendo historial de pagos...')
        pagos = leer_pagos(conn)

        conn.Close()

        step('[4/4] Generando panel-admin.html...')
        data = construir_data(socios_list, disc_por_socio, socios_con_srv, deuda, pagos)
        generar_html(data)
        c = data['_conteo']
        step(f'  Total:{data["_total"]}  Al dia:{c["al_dia"]}  Deudores:{c["deudor"]}  Bajas:{c["baja"]}')
        step(f'  Disciplinas: {data["_disciplinas"]}')

        step('[5/5] Git push...')
        git_push()

        step(f'OK - Tiempo total: {(datetime.now() - inicio).seconds}s')

    except Exception as e:
        log.exception(f'ERROR: {e}')
        sys.exit(1)


if __name__ == '__main__':
    main()
