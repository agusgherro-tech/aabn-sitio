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
    filas_activos, filas_baja, disc_set = [], [], set()
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

        fila = {
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
        }

        if estado_final == 'baja':
            filas_baja.append(fila)
        else:
            filas_activos.append(fila)

    return {
        '_filas':       filas_activos,
        '_filas_baja':  filas_baja,
        '_conteo':      conteo,
        '_total':       len(filas_activos),
        '_total_baja':  len(filas_baja),
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
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {
      theme: {
        extend: {
          colors: {
            verde:{50:"#f0fdf4",100:"#dcfce7",200:"#bbf7d0",300:"#86efac",
                   400:"#4ade80",500:"#22903a",600:"#1a672a",700:"#1d7a31",
                   800:"#1a672a",900:"#154C20"}
          },
          fontFamily: {
            sans:   ["Rag","Segoe UI","Arial","sans-serif"],
            expose: ["Expose","Arial Black","sans-serif"],
          }
        }
      }
    }
  </script>
  <style>
    @font-face{font-family:"Expose";src:url("fonts/Expose-Black.woff2") format("woff2");font-weight:900;}
    @font-face{font-family:"Expose";src:url("fonts/Expose-Bold.woff2") format("woff2");font-weight:700;}
    @font-face{font-family:"Expose";src:url("fonts/Expose-Regular.woff2") format("woff2");font-weight:400;}
    @font-face{font-family:"Rag";src:url("fonts/Rag-Regular.woff2") format("woff2"),url("fonts/Rag-Regular.woff") format("woff");font-weight:400;font-style:normal;}
    @font-face{font-family:"Rag";src:url("fonts/Rag-Bold.woff2") format("woff2"),url("fonts/Rag-Bold.woff") format("woff");font-weight:700;font-style:normal;}
    @font-face{font-family:"Rag";src:url("fonts/Rag-Black.woff2") format("woff2"),url("fonts/Rag-Black.woff") format("woff");font-weight:900;font-style:normal;}
    *{box-sizing:border-box;}
    html,body{height:100%;margin:0;}
    body{background:#f3f4f6;color:#111827;}

    .badge-al_dia{background:rgba(16,185,129,.12);color:#047857;border:1px solid rgba(16,185,129,.25);}
    .badge-deudor{background:rgba(239,68,68,.1);color:#dc2626;border:1px solid rgba(239,68,68,.2);}
    .badge-baja  {background:rgba(0,0,0,.05);color:rgba(0,0,0,.4);border:1px solid rgba(0,0,0,.1);}

    tr.data-row:hover td{background:rgba(0,0,0,.025);}
    tr.data-row:nth-child(even) td{background:rgba(0,0,0,.03);}
    tr.data-row td{transition:background .1s;}
    tr.data-row{border-bottom:1px solid rgba(0,0,0,.06);}

    .sortable{cursor:pointer;user-select:none;transition:color .15s;}
    .sortable:hover{color:rgba(0,0,0,.7)!important;}
    thead th{position:sticky;top:0;z-index:10;}

    .table-wrap{max-height:calc(100vh - 300px);overflow:auto;scrollbar-width:thin;scrollbar-color:rgba(0,0,0,.15) transparent;}
    .table-wrap::-webkit-scrollbar{width:5px;height:5px;}
    .table-wrap::-webkit-scrollbar-track{background:transparent;}
    .table-wrap::-webkit-scrollbar-thumb{background:rgba(0,0,0,.15);border-radius:10px;}

    .input-f{background:#fff;border:1px solid rgba(0,0,0,.12);border-radius:10px;
             padding:7px 13px;font-size:12px;color:rgba(0,0,0,.7);outline:none;
             transition:border-color .2s,box-shadow .2s;font-family:inherit;}
    .input-f:focus{border-color:rgba(26,103,42,.5);box-shadow:0 0 0 3px rgba(26,103,42,.08);}
    .input-f::placeholder{color:rgba(0,0,0,.3);}
    .input-f option{background:#fff;color:#374151;}

    /* ── Panel de sugerencias de búsqueda ── */
    #sugg-panel{position:absolute;left:0;right:0;top:calc(100% + 6px);background:#fff;border:1px solid rgba(0,0,0,.1);border-radius:14px;box-shadow:0 10px 36px rgba(0,0,0,.12);z-index:100;overflow:hidden;display:none;}
    .sugg-header{padding:8px 16px;background:#f8fafb;border-bottom:1px solid rgba(0,0,0,.06);font-size:10px;font-weight:700;letter-spacing:1.5px;color:#9ca3af;text-transform:uppercase;}
    .sugg-row{display:flex;align-items:center;gap:12px;padding:9px 16px;border-bottom:1px solid rgba(0,0,0,.04);cursor:pointer;transition:background .1s;}
    .sugg-row:last-child{border-bottom:none;}
    .sugg-row:hover{background:#f0fdf4;}
    .sugg-avatar{width:30px;height:30px;background:#1a672a;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;color:#fff;flex-shrink:0;}
    .sugg-name{font-size:13px;font-weight:600;color:#111827;}
    .sugg-meta{font-size:11px;color:#6b7280;margin-top:1px;}
    .sugg-cat{display:inline-block;font-size:10px;font-weight:700;background:#eff6ff;color:#1d4ed8;border:1px solid rgba(29,78,216,.18);padding:1px 5px;border-radius:5px;margin-right:3px;}
    .sugg-ok{flex-shrink:0;font-size:10px;font-weight:700;padding:3px 8px;border-radius:6px;background:#f0fdf4;color:#16a34a;border:1px solid rgba(22,163,74,.2);}
    .sugg-debe{flex-shrink:0;font-size:10px;font-weight:700;padding:3px 8px;border-radius:6px;background:#fef2f2;color:#dc2626;border:1px solid rgba(220,38,38,.2);}
    #buscar-wrap{position:relative;}

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
    .nav-active{background:rgba(26,103,42,.35)!important;border-color:rgba(74,222,128,.3)!important;color:#86efac!important;}

    td,th{white-space:nowrap;}
  </style>
</head>
<body class="font-sans antialiased">

<div style="display:flex;height:100vh;overflow:hidden;">

<!-- ── SIDEBAR ── -->
<aside style="width:220px;flex-shrink:0;background:#154C20;border-right:1px solid rgba(255,255,255,.08);display:flex;flex-direction:column;z-index:40;">

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

    <a href="asistencia.html" class="nav-item">
      <svg style="width:16px;height:16px;flex-shrink:0" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/>
      </svg>
      Socios Asistencia
    </a>

    <div style="height:1px;background:rgba(255,255,255,.05);margin:8px 0"></div>
    <div style="font-size:9px;font-weight:700;letter-spacing:.15em;text-transform:uppercase;padding:0 8px;margin-bottom:8px;color:rgba(255,255,255,.18)">Gestión</div>
    <button onclick="mostrarVista('socios')" id="nav-socios" class="nav-item nav-active">
      <svg style="width:16px;height:16px;flex-shrink:0" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2M9 7a4 4 0 100 8 4 4 0 000-8zM23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75"/>
      </svg>
      Socios activos
    </button>
    <button onclick="mostrarVista('bajas')" id="nav-bajas" class="nav-item">
      <svg style="width:16px;height:16px;flex-shrink:0" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" d="M18.364 18.364A9 9 0 005.636 5.636m12.728 12.728A9 9 0 015.636 5.636m12.728 12.728L5.636 5.636"/>
      </svg>
      <span style="flex:1;text-align:left">Dados de baja</span>
      <span id="nav-baja-cnt" style="font-size:10px;background:rgba(255,255,255,.07);border-radius:20px;padding:1px 7px;color:rgba(255,255,255,.3);font-weight:700"></span>
    </button>
    <a href="estado-resultados.html" class="nav-item">
      <svg style="width:16px;height:16px;flex-shrink:0" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/>
      </svg>
      Finanzas
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

  <header style="flex-shrink:0;height:56px;display:flex;align-items:center;justify-content:space-between;padding:0 32px;border-bottom:1px solid rgba(0,0,0,.08);background:rgba(255,255,255,.95);backdrop-filter:blur(12px);z-index:30">
    <div style="display:flex;align-items:center;gap:12px">
      <h1 id="header-titulo" class="font-expose font-black" style="font-size:15px;color:#154C20;letter-spacing:-.01em">Dashboard Socios</h1>
      <span style="font-size:12px;color:rgba(0,0,0,.35)">Asociación Atlética Banda Norte</span>
    </div>
    <div style="font-size:12px;color:rgba(0,0,0,.45)">
      Actualizado: <span id="fecha-gen" style="font-weight:600;color:rgba(0,0,0,.65);margin-left:4px"></span>
    </div>
  </header>

  <div style="flex:1;overflow-y:auto;padding:28px 32px">

<!-- ══ VISTA SOCIOS ACTIVOS ══ -->
<div id="view-socios">

    <!-- STAT CARDS -->
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:24px">

      <div style="background:#fff;border:1px solid rgba(0,0,0,.07);border-radius:16px;padding:20px;box-shadow:0 1px 4px rgba(0,0,0,.06)">
        <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:rgba(0,0,0,.4);margin-bottom:14px">Padrón activo</div>
        <div id="c-total" class="card-num" style="color:#111827"></div>
        <div style="font-size:11px;color:rgba(0,0,0,.35);margin-top:10px">socios activos</div>
      </div>

      <div style="background:#fff;border:1px solid rgba(28,116,62,.35);border-radius:16px;padding:20px;position:relative;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.06)">
        <div style="position:absolute;top:16px;right:16px;width:6px;height:6px;border-radius:50%;background:#28904f"></div>
        <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:#1a672a;margin-bottom:14px">Al día</div>
        <div id="c-aldia" class="card-num" style="color:#1a672a"></div>
        <div id="p-aldia" style="font-size:11px;color:rgba(26,103,42,.5);margin-top:10px"></div>
      </div>

      <div style="background:#fff;border:1px solid rgba(185,28,28,.25);border-radius:16px;padding:20px;position:relative;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.06)">
        <div style="position:absolute;top:16px;right:16px;width:6px;height:6px;border-radius:50%;background:#ef4444"></div>
        <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:#dc2626;margin-bottom:14px">Deudores</div>
        <div id="c-deudor" class="card-num" style="color:#dc2626"></div>
        <div id="p-deudor" style="font-size:11px;color:rgba(220,38,38,.5);margin-top:10px"></div>
      </div>

      <div style="background:#fff;border:1px solid rgba(251,146,60,.3);border-radius:16px;padding:20px;position:relative;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.06)">
        <div style="position:absolute;top:16px;right:16px;width:6px;height:6px;border-radius:50%;background:#f97316"></div>
        <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:#ea580c;margin-bottom:14px">Deuda total</div>
        <div id="c-deuda" class="card-num-sm" style="color:#ea580c"></div>
        <div id="p-cobrado" style="font-size:11px;color:rgba(234,88,12,.5);margin-top:10px"></div>
      </div>

    </div>

    <!-- TABLE CARD -->
    <div style="background:#fff;border:1px solid rgba(0,0,0,.07);border-radius:16px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.06)">

      <div style="padding:20px 24px;border-bottom:1px solid rgba(0,0,0,.07)">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px">
          <div>
            <h2 class="font-expose font-bold" style="font-size:15px;color:#154C20;letter-spacing:-.01em">Padrón Completo</h2>
            <p style="font-size:11px;color:rgba(0,0,0,.4);margin-top:2px">Click en columna para ordenar · <span id="conteo-f" style="color:#1a672a"></span></p>
          </div>
        </div>
        <div style="display:flex;flex-wrap:wrap;gap:8px">
          <div id="buscar-wrap" style="flex:1;min-width:200px;position:relative;">
            <input id="f-buscar" oninput="filtrar()" type="text"
              placeholder="Buscar nombre, DNI, Nº, email, teléfono…"
              class="input-f" style="width:100%">
            <div id="sugg-panel">
              <div class="sugg-header" id="sugg-title">Coincidencias</div>
              <div id="sugg-list"></div>
            </div>
          </div>
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
          <button onclick="limpiar()" class="input-f" style="cursor:pointer;padding:7px 16px;color:rgba(0,0,0,.5)">
            Limpiar
          </button>
        </div>
      </div>

      <div class="table-wrap">
        <table style="width:100%;font-size:13px;border-collapse:collapse">
          <thead>
            <tr style="border-bottom:1px solid rgba(0,0,0,.07);background:#f1f5f9">
              <th class="sortable px-3 py-3 text-center" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(0,0,0,.45)" onclick="ordenar('nro_socio')"># ↕</th>
              <th class="sortable px-4 py-3 text-left" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(0,0,0,.45)" onclick="ordenar('nombre')">Nombre ↕</th>
              <th class="sortable px-4 py-3 text-left" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(0,0,0,.45)" onclick="ordenar('dni')">DNI ↕</th>
              <th class="px-4 py-3 text-left" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(0,0,0,.45)">Teléfono</th>
              <th class="px-4 py-3 text-left" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(0,0,0,.45)">Email</th>
              <th class="px-4 py-3 text-center" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(0,0,0,.45)">Estado</th>
              <th class="px-4 py-3 text-left" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(0,0,0,.45)">Disciplina</th>
              <th class="sortable px-4 py-3 text-center" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(0,0,0,.45)" onclick="ordenar('cant_pend')">Cuotas ↕</th>
              <th class="sortable px-4 py-3 text-right" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(0,0,0,.45)" onclick="ordenar('deuda_total')">Deuda ↕</th>
              <th class="sortable px-4 py-3 text-left" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(0,0,0,.45)" onclick="ordenar('ultimo_pago')">Últ. pago ↕</th>
              <th class="sortable px-4 py-3 text-right" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(0,0,0,.45)" onclick="ordenar('cobrado_2026')">Cobrado 2026 ↕</th>
              <th class="px-4 py-3 text-center" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(0,0,0,.45)">Déb.</th>
            </tr>
          </thead>
          <tbody id="tbody"></tbody>
        </table>
      </div>

      <div style="padding:12px 24px;border-top:1px solid rgba(0,0,0,.07);display:flex;justify-content:space-between;font-size:11px;color:rgba(0,0,0,.4)">
        <span>Fuente: AABN_d.accdb · Siwin</span>
        <span>Generado: <span id="fecha-pie" style="font-weight:600;color:rgba(0,0,0,.55)"></span></span>
      </div>

    </div>
</div><!-- /view-socios -->

<!-- ══ VISTA DADOS DE BAJA ══ -->
<div id="view-bajas" style="display:none">

    <!-- STAT CARD BAJAS -->
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:24px">
      <div style="background:#fff;border:1px solid rgba(0,0,0,.07);border-radius:16px;padding:20px;box-shadow:0 1px 4px rgba(0,0,0,.06)">
        <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:rgba(0,0,0,.4);margin-bottom:14px">Dados de baja</div>
        <div id="b-total" class="card-num" style="color:#64748b"></div>
        <div style="font-size:11px;color:rgba(0,0,0,.35);margin-top:10px">sin servicio activo</div>
      </div>
      <div style="background:#fff;border:1px solid rgba(0,0,0,.07);border-radius:16px;padding:20px;box-shadow:0 1px 4px rgba(0,0,0,.06)">
        <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:rgba(0,0,0,.4);margin-bottom:14px">Con último pago</div>
        <div id="b-conpago" class="card-num" style="color:#64748b"></div>
        <div style="font-size:11px;color:rgba(0,0,0,.35);margin-top:10px">alguna vez pagaron</div>
      </div>
      <div style="background:#fff;border:1px solid rgba(0,0,0,.07);border-radius:16px;padding:20px;box-shadow:0 1px 4px rgba(0,0,0,.06)">
        <div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:rgba(0,0,0,.4);margin-bottom:14px">Con disciplina</div>
        <div id="b-condisc" class="card-num" style="color:#64748b"></div>
        <div style="font-size:11px;color:rgba(0,0,0,.35);margin-top:10px">tenían deporte asignado</div>
      </div>
    </div>

    <!-- TABLE BAJAS -->
    <div style="background:#fff;border:1px solid rgba(0,0,0,.07);border-radius:16px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.06)">
      <div style="padding:20px 24px;border-bottom:1px solid rgba(0,0,0,.07)">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px">
          <div>
            <h2 class="font-expose font-bold" style="font-size:15px;color:#154C20;letter-spacing:-.01em">Socios dados de baja</h2>
            <p style="font-size:11px;color:rgba(0,0,0,.4);margin-top:2px">Sin servicio activo en Siwin · <span id="b-conteo-f" style="color:rgba(0,0,0,.5)"></span></p>
          </div>
        </div>
        <div style="display:flex;flex-wrap:wrap;gap:8px">
          <input id="b-buscar" oninput="filtrarBajas()" type="text"
            placeholder="Buscar nombre, DNI, Nº, teléfono…"
            class="input-f" style="flex:1;min-width:200px">
          <button onclick="limpiarBajas()" class="input-f" style="cursor:pointer;padding:7px 16px;color:rgba(0,0,0,.5)">
            Limpiar
          </button>
        </div>
      </div>
      <div class="table-wrap">
        <table style="width:100%;font-size:13px;border-collapse:collapse">
          <thead>
            <tr style="border-bottom:1px solid rgba(0,0,0,.07);background:#f1f5f9">
              <th class="sortable px-3 py-3 text-center" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(0,0,0,.45)" onclick="ordenarBajas('nro_socio')"># ↕</th>
              <th class="sortable px-4 py-3 text-left" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(0,0,0,.45)" onclick="ordenarBajas('nombre')">Nombre ↕</th>
              <th class="sortable px-4 py-3 text-left" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(0,0,0,.45)" onclick="ordenarBajas('dni')">DNI ↕</th>
              <th class="px-4 py-3 text-left" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(0,0,0,.45)">Teléfono</th>
              <th class="px-4 py-3 text-left" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(0,0,0,.45)">Disciplina</th>
              <th class="sortable px-4 py-3 text-left" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(0,0,0,.45)" onclick="ordenarBajas('ultimo_pago')">Últ. pago ↕</th>
              <th class="sortable px-4 py-3 text-right" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(0,0,0,.45)" onclick="ordenarBajas('cobrado_2026')">Cobrado 2026 ↕</th>
              <th class="sortable px-4 py-3 text-left" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:rgba(0,0,0,.45)" onclick="ordenarBajas('fecha_ing')">Ing. ↕</th>
            </tr>
          </thead>
          <tbody id="tbody-bajas"></tbody>
        </table>
      </div>
      <div style="padding:12px 24px;border-top:1px solid rgba(0,0,0,.07);display:flex;justify-content:space-between;font-size:11px;color:rgba(0,0,0,.4)">
        <span>Fuente: AABN_d.accdb · Siwin</span>
        <span>Generado: <span id="b-fecha-pie" style="font-weight:600;color:rgba(0,0,0,.55)"></span></span>
      </div>
    </div>
</div><!-- /view-bajas -->

  </div>
</div>

</div>

</div>

<script>
const DATA = PLACEHOLDER_DATA;

// ── Auth ──────────────────────────────────────────────────────────────────
const admin = JSON.parse(sessionStorage.getItem("admin") || "null");
if (!admin) { window.location.href = "login.html"; }
else {
  const ai = document.getElementById("admin-info"); ai.style.display = "flex";
  document.getElementById("admin-nombre").textContent = admin.nombre;
  document.getElementById("admin-rol").textContent    = admin.rol;
}
function cerrarSesion() { sessionStorage.removeItem("admin"); window.location.href = "login.html"; }

// ── Fechas ─────────────────────────────────────────────────────────────────
const gen = DATA._generado || "";
document.getElementById("fecha-gen").textContent = gen;
document.getElementById("fecha-pie").textContent = gen;
document.getElementById("b-fecha-pie").textContent = gen;

// ── Tarjetas socios activos ────────────────────────────────────────────────
const c   = DATA._conteo;
const tot = DATA._total;
const filasTodas = DATA._filas;
const deudaTotal  = filasTodas.reduce((s, r) => s + (r.deuda_total  || 0), 0);
const cobrado2026 = filasTodas.reduce((s, r) => s + (r.cobrado_2026 || 0), 0);

document.getElementById("c-total").textContent   = tot.toLocaleString("es-AR");
document.getElementById("c-aldia").textContent   = (c.al_dia||0).toLocaleString("es-AR");
document.getElementById("c-deudor").textContent  = (c.deudor||0).toLocaleString("es-AR");
document.getElementById("c-deuda").textContent   = "$" + Math.round(deudaTotal/1000).toLocaleString("es-AR") + "K";
document.getElementById("p-aldia").textContent   = Math.round((c.al_dia||0)*100/tot) + "% del padrón";
document.getElementById("p-deudor").textContent  = Math.round((c.deudor||0)*100/tot) + "% del padrón";
document.getElementById("p-cobrado").textContent = "Cobrado: $" + Math.round(cobrado2026/1000).toLocaleString("es-AR") + "K";

// ── Tarjetas bajas ─────────────────────────────────────────────────────────
const filasTodasBaja = DATA._filas_baja || [];
const totalBaja = DATA._total_baja || 0;
const bajaConPago = filasTodasBaja.filter(r => r.ultimo_pago).length;
const bajaConDisc = filasTodasBaja.filter(r => r.disciplinas).length;

document.getElementById("b-total").textContent   = totalBaja.toLocaleString("es-AR");
document.getElementById("b-conpago").textContent = bajaConPago.toLocaleString("es-AR");
document.getElementById("b-condisc").textContent = bajaConDisc.toLocaleString("es-AR");
document.getElementById("nav-baja-cnt").textContent = totalBaja.toLocaleString("es-AR");

// ── Select disciplinas ─────────────────────────────────────────────────────
const selDisc = document.getElementById("f-disc");
(DATA._disciplinas || []).forEach(d => {
  const o = document.createElement("option");
  o.value = d; o.textContent = d;
  selDisc.appendChild(o);
});

// ── Navegación de vistas ───────────────────────────────────────────────────
function mostrarVista(v) {
  document.getElementById("view-socios").style.display = v === "socios" ? "" : "none";
  document.getElementById("view-bajas").style.display  = v === "bajas"  ? "" : "none";
  document.getElementById("nav-socios").classList.toggle("nav-active", v === "socios");
  document.getElementById("nav-bajas").classList.toggle("nav-active",  v === "bajas");
  const titulos = { socios: "Dashboard Socios", bajas: "Socios dados de baja" };
  document.getElementById("header-titulo").textContent = titulos[v];
}

// ══════════════════════════════════════════════════════════════════════════
// TABLA SOCIOS ACTIVOS
// ══════════════════════════════════════════════════════════════════════════
let filasFiltradas = [...filasTodas];
let ordenCol = "nombre", ordenAsc = true;

function filtrar() {
  const qRaw   = document.getElementById("f-buscar").value.trim();
  const q      = qRaw.toLowerCase();
  const estado = document.getElementById("f-estado").value;
  const disc   = document.getElementById("f-disc").value;
  const deb    = document.getElementById("f-deb").value;

  actualizarSugg(qRaw);

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
  document.getElementById("sugg-panel").style.display = "none";
  renderTabla();
}

// ── Drive: categorías por DNI ───────────────────────────────────────────────
const DRIVE_SHEETS = [
  { nombre:"Fútbol Masculino", emoji:"⚽", id:"1Y6v5HeQxe-OtRgqoI6k473I_8hxFQPfT2SHatKXMHRE", tabs:["04/26","03/26","02/26"] },
  { nombre:"Fútbol Femenino",  emoji:"⚽", id:"1E3u_GFRI4J5AqdTXsETiUXKf_CRnttT5P5TIKOalPZE", tabs:["04/26","03/26","02/26"] },
  { nombre:"Básquet Masc.",    emoji:"🏀", id:"1yrGvGBjh3j-qZvBwXmUZoRIfZgznoejLjs9q2uS21Bg", tabs:["04/26","03/26","02/26","BASQUET AL 20/2"] },
  { nombre:"Básquet Fem.",     emoji:"🏀", id:"160RkywlXeVOZSh8H4HX1cIDmIJ_yPCjR2dmMSZ8BVf8", tabs:["04/26","03/26","02/26"] },
  { nombre:"Gimnasia",         emoji:"🤸", id:"1ugDHlZWeRaB_2YNr0wp7hi85MKbGkVzDKfJ8ncK0p74", tabs:["04/26","03/26","02/26"] },
  { nombre:"Patín",            emoji:"⛸️", id:"1TkL0PdhjSO0vj-MxFMg7NGpsl9tf5ZYDqJlQvWLME_A", tabs:["04/26","03/26","02/26"] },
];
const dniCatMap = {};

function normDniDrive(v){ return String(v||"").replace(/[.\\s\\-]/g,"").trim(); }

function parsearCSVDrive(txt){
  const filas=[];let dentro=false,campo="",fila=[];
  for(let i=0;i<txt.length;i++){
    const c=txt[i];
    if(c==='"'){dentro=!dentro;continue;}
    if(!dentro&&c===","){fila.push(campo.trim());campo="";continue;}
    if(!dentro&&(c==="\\n"||c==="\\r")){
      if(campo.trim()||fila.length){fila.push(campo.trim());filas.push(fila);}
      campo="";fila=[];if(txt[i+1]==="\\n")i++;continue;
    }
    campo+=c;
  }
  if(campo||fila.length){fila.push(campo.trim());filas.push(fila);}
  return filas;
}

async function cargarCategoriasDrive(){
  for(const sh of DRIVE_SHEETS){
    for(const tab of sh.tabs){
      try{
        const url=`https://docs.google.com/spreadsheets/d/${sh.id}/gviz/tq?tqx=out:csv&sheet=${encodeURIComponent(tab)}`;
        const r=await fetch(url,{cache:"no-store"});
        if(!r.ok) continue;
        const txt=await r.text();
        if(txt.length<100||txt.startsWith("<!")) continue;
        const filas=parsearCSVDrive(txt);
        let hIdx=-1;
        for(let i=0;i<Math.min(filas.length,8);i++)
          if(filas[i].some(c=>c.toUpperCase().includes("NOMBRE")&&c.toUpperCase().includes("APELLIDO"))){hIdx=i;break;}
        if(hIdx<0) continue;
        const hdr=filas[hIdx];
        let iDni=-1,iCat=-1;
        hdr.forEach((h,i)=>{
          const u=h.toUpperCase().trim();
          if(u==="DNI") iDni=i;
          if(u==="CATEGORÍA"||u==="CATEGORIA") iCat=i;
        });
        if(iDni<0) iDni=4; if(iCat<0) iCat=2;
        for(const f of filas.slice(hIdx+1)){
          const dni=normDniDrive(f[iDni]||"");
          if(!dni) continue;
          const cat=(f[iCat]||"").trim();
          if(cat) dniCatMap[dni]={cat,disc:sh.nombre,emoji:sh.emoji};
        }
        break; // tab exitosa, pasar al siguiente sheet
      }catch{}
    }
  }
}
cargarCategoriasDrive();

// ── Panel de sugerencias rápidas ────────────────────────────────────────────
function fmtPesoSwin(n){return n?("$"+Math.round(n).toLocaleString("es-AR")):"$0";}

function actualizarSugg(q){
  const panel=document.getElementById("sugg-panel");
  if(!q||q.length<2){panel.style.display="none";return;}
  const ql=q.replace(/[.\\s\\-]/g,"").toLowerCase();
  const qn=q.toLowerCase();
  const res=filasTodas.filter(r=>
    (r.nombre||"").toLowerCase().includes(qn)||
    (r.dni||"").includes(ql)||
    String(r.nro_socio||"").includes(ql)
  ).slice(0,8);
  if(!res.length){panel.style.display="none";return;}
  document.getElementById("sugg-title").textContent=res.length+" coincidencia"+(res.length>1?"s":"");
  document.getElementById("sugg-list").innerHTML=res.map(r=>{
    const driveInfo=dniCatMap[normDniDrive(r.dni||"")];
    const catHtml=driveInfo?`<span class="sugg-cat">${driveInfo.cat}</span>`:"";
    const discDrive=driveInfo?` ${driveInfo.emoji} ${driveInfo.disc}`:"";
    const estadoHtml=r.estado_final==="deudor"
      ?`<span class="sugg-debe">DEBE</span>`
      :`<span class="sugg-ok">AL DÍA</span>`;
    return `<div class="sugg-row" onclick="irAFila(${r.nro_socio||0})">
      <div class="sugg-avatar">${(r.nombre||"?").charAt(0).toUpperCase()}</div>
      <div style="flex:1;min-width:0">
        <div class="sugg-name">${r.nombre||"—"}</div>
        <div class="sugg-meta">${r.dni?"DNI: "+r.dni+" · ":""}${catHtml}${r.disciplinas||discDrive||"—"}</div>
      </div>
      ${estadoHtml}
    </div>`;
  }).join("");
  panel.style.display="";
}

function irAFila(nroSocio){
  document.getElementById("sugg-panel").style.display="none";
  const fila=document.querySelector(`tr[data-nro="${nroSocio}"]`);
  if(fila){fila.scrollIntoView({behavior:"smooth",block:"center"});fila.style.background="#fef9c3";setTimeout(()=>fila.style.background="",1800);}
}

document.addEventListener("click",e=>{
  if(!document.getElementById("buscar-wrap").contains(e.target))
    document.getElementById("sugg-panel").style.display="none";
});

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
    tbody.innerHTML = `<tr><td colspan="12" class="text-center py-16 text-sm" style="color:rgba(0,0,0,.4)">Sin resultados para los filtros aplicados</td></tr>`;
    return;
  }

  tbody.innerHTML = filasFiltradas.map(r => {
    const deudaFmt = (r.deuda_total || 0) > 0
      ? `<span style="font-weight:700;color:#dc2626">$${Math.round(r.deuda_total).toLocaleString("es-AR")}</span>`
      : `<span style="color:rgba(0,0,0,.18)">—</span>`;
    const cobFmt = (r.cobrado_2026 || 0) > 0
      ? `<span style="font-weight:600;color:#1a672a">$${Math.round(r.cobrado_2026).toLocaleString("es-AR")}</span>`
      : `<span style="color:rgba(0,0,0,.18)">—</span>`;
    const discFmt = r.disciplinas
      ? `<span class="tag-disc">${r.disciplinas}</span>`
      : `<span style="color:rgba(0,0,0,.18)">—</span>`;
    const telFmt = r.telefono
      ? `<a href="tel:${r.telefono}" style="color:#2563eb">${r.telefono}</a>`
      : `<span style="color:rgba(0,0,0,.18)">—</span>`;
    const mailFmt = r.email
      ? `<a href="mailto:${r.email}" style="color:#2563eb;font-size:11px">${r.email}</a>`
      : `<span style="color:rgba(0,0,0,.18)">—</span>`;
    const debFmt = r.deb_auto
      ? `<span class="tag-deb">DBT</span>`
      : `<span style="color:rgba(0,0,0,.18)">—</span>`;
    const cantFmt = (r.cant_pend || 0) > 0
      ? `<span style="font-weight:700;color:#dc2626">${r.cant_pend}</span>`
      : `<span style="color:rgba(0,0,0,.18)">—</span>`;
    const badgeCls = "badge-" + (r.estado_final || "baja");
    return `<tr class="data-row" data-nro="${r.nro_socio||0}" style="transition:background .4s">
      <td class="px-3 py-3 text-center text-xs font-mono" style="color:rgba(0,0,0,.35)">${r.nro_socio||"—"}</td>
      <td class="px-4 py-3 font-semibold" style="color:#111827">${r.nombre}</td>
      <td class="px-4 py-3 font-mono text-xs" style="color:rgba(0,0,0,.4)">${r.dni||"—"}</td>
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
      <td class="px-4 py-3 text-xs" style="color:rgba(0,0,0,.4)">${r.ultimo_pago||"—"}</td>
      <td class="px-4 py-3 text-right">${cobFmt}</td>
      <td class="px-4 py-3 text-center">${debFmt}</td>
    </tr>`;
  }).join("");
}

// ══════════════════════════════════════════════════════════════════════════
// TABLA SOCIOS DADOS DE BAJA
// ══════════════════════════════════════════════════════════════════════════
let bajasFiltradas = [...filasTodasBaja];
let ordenBajaCol = "nombre", ordenBajaAsc = true;

function filtrarBajas() {
  const q = document.getElementById("b-buscar").value.toLowerCase().trim();
  bajasFiltradas = filasTodasBaja.filter(r => {
    if (!q) return true;
    const nro = String(r.nro_socio || "");
    const tel = (r.telefono || "").toLowerCase();
    return r.nombre.toLowerCase().includes(q) || r.dni.includes(q) ||
           nro.includes(q) || tel.includes(q);
  });
  renderBajas();
}

function limpiarBajas() {
  document.getElementById("b-buscar").value = "";
  bajasFiltradas = [...filasTodasBaja];
  renderBajas();
}

function ordenarBajas(col) {
  if (ordenBajaCol === col) ordenBajaAsc = !ordenBajaAsc;
  else { ordenBajaCol = col; ordenBajaAsc = true; }
  const numCols = ["nro_socio","cobrado_2026"];
  bajasFiltradas.sort((a, b) => {
    let va = a[col], vb = b[col];
    if (numCols.includes(col)) { va = va||0; vb = vb||0; }
    else { va = (va||"").toString().toLowerCase(); vb = (vb||"").toString().toLowerCase(); }
    if (va < vb) return ordenBajaAsc ? -1 : 1;
    if (va > vb) return ordenBajaAsc ?  1 : -1;
    return 0;
  });
  renderBajas();
}

function renderBajas() {
  const tbody = document.getElementById("tbody-bajas");
  const conteoEl = document.getElementById("b-conteo-f");
  if (conteoEl) conteoEl.textContent = bajasFiltradas.length.toLocaleString("es-AR") + " socios";

  if (!bajasFiltradas.length) {
    tbody.innerHTML = `<tr><td colspan="8" class="text-center py-16 text-sm" style="color:rgba(0,0,0,.4)">Sin resultados</td></tr>`;
    return;
  }

  tbody.innerHTML = bajasFiltradas.map(r => {
    const cobFmt = (r.cobrado_2026 || 0) > 0
      ? `<span style="font-weight:600;color:rgba(26,103,42,.6)">$${Math.round(r.cobrado_2026).toLocaleString("es-AR")}</span>`
      : `<span style="color:rgba(0,0,0,.18)">—</span>`;
    const discFmt = r.disciplinas
      ? `<span class="tag-disc" style="opacity:.6">${r.disciplinas}</span>`
      : `<span style="color:rgba(0,0,0,.18)">—</span>`;
    const telFmt = r.telefono
      ? `<a href="tel:${r.telefono}" style="color:rgba(37,99,235,.6)">${r.telefono}</a>`
      : `<span style="color:rgba(0,0,0,.18)">—</span>`;
    return `<tr class="data-row" style="opacity:.75">
      <td class="px-3 py-3 text-center text-xs font-mono" style="color:rgba(0,0,0,.28)">${r.nro_socio||"—"}</td>
      <td class="px-4 py-3 font-semibold" style="color:rgba(0,0,0,.55)">${r.nombre}</td>
      <td class="px-4 py-3 font-mono text-xs" style="color:rgba(0,0,0,.35)">${r.dni||"—"}</td>
      <td class="px-4 py-3 text-xs">${telFmt}</td>
      <td class="px-4 py-3">${discFmt}</td>
      <td class="px-4 py-3 text-xs" style="color:rgba(0,0,0,.35)">${r.ultimo_pago||"—"}</td>
      <td class="px-4 py-3 text-right">${cobFmt}</td>
      <td class="px-4 py-3 text-xs" style="color:rgba(0,0,0,.35)">${r.fecha_ing||"—"}</td>
    </tr>`;
  }).join("");
}

// ── Init ──────────────────────────────────────────────────────────────────
ordenar("nombre");
ordenarBajas("nombre");
</script>
</body>
</html>
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
