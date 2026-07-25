#!/usr/bin/env bash
# Gestor de datasets efímeros para Nikodym.
#
# Filosofía: el disco es escaso, los datasets son reproducibles. Se baja lo que se va a
# usar ahora, se prueba, se borra. Si hace falta otra vez, se vuelve a bajar con una línea.
# Lo único permanente es este script + README.md + catalogo.csv (~50 KB).
#
#   ./descargar.sh ls              estado de todo: qué está en disco y cuánto pesa
#   ./descargar.sh get <clave>...  baja uno o varios
#   ./descargar.sh rm  <clave>...  borra uno o varios (pide confirmación)
#   ./descargar.sh nucleo          baja el set liviano permanente (~90 MB)
#   ./descargar.sh espacio         disco libre + ranking de lo que ocupa
#   ./descargar.sh manual          fuentes que exigen navegador o registro
#   ./descargar.sh inventario      regenera INVENTARIO.md con lo que hay en disco
#
# Ejemplo de ciclo típico:
#   ./descargar.sh get lending_club_reject     # 3,8 GB
#   ... trabajas el módulo de reject inference ...
#   ./descargar.sh rm lending_club_reject      # recuperas el disco
#
# Relevado y verificado el 2026-07-25.

set -uo pipefail
BASE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAW="$BASE/raw"

# ─────────────────────────────────────────────────────────────────────────────
# REGISTRO:  clave | subruta bajo raw/ | metodo | origen | peso aprox
#   metodos: curl | kagg_d (dataset) | kagg_c (competencia) | multi (varios curl)
# ─────────────────────────────────────────────────────────────────────────────
UCI="https://archive.ics.uci.edu/static/public"
CRA="http://www.creditriskanalytics.net/uploads/1/9/5/1/19511601"

REGISTRO=$(cat <<'EOF'
hmeq|scorecard/hmeq.csv|curl|CRA/hmeq.csv|400 KB
german|scorecard/german_credit.zip|curl|UCI/144/statlog+german+credit+data.zip|32 KB
south_german|scorecard/south_german_credit.zip|curl|UCI/522/south+german+credit.zip|16 KB
taiwan|scorecard/taiwan_credit_cards.zip|curl|UCI/350/default+of+credit+card+clients.zip|6 MB
credit_approval|scorecard/credit_approval.zip|curl|UCI/27/credit+approval.zip|16 KB
australian|scorecard/australian_credit.zip|curl|UCI/143/statlog+australian+credit+approval.zip|12 KB
polish|corporativo/polish_bankruptcy.zip|curl|UCI/365/polish+companies+bankruptcy+data.zip|9 MB
taiwan_bank|corporativo/taiwanese_bankruptcy.zip|curl|UCI/572/taiwanese+bankruptcy+prediction.zip|5 MB
ratings|corporativo/ratings.csv|curl|CRA/ratings.csv|12 KB
adult|fairness/adult_census.zip|curl|UCI/2/adult.zip|640 KB
lgd|lgd/lgd.csv|curl|CRA/lgd.csv|188 KB
mortgage|ifrs9/mortgage.csv|rar|CRA/mortgage_csv.rar|68 MB
bondora|lgd/bondora_loan_dataset.xlsx|curl|https://sabanners001.blob.core.windows.net/statistics/public/loan_dataset_investor.xlsx|160 MB
fed|stress/fed|multi|fed|2 MB
eba_st|stress/eba|multi|eba_st|133 MB
eba_te|basilea|multi|eba_te|245 MB
fred|macro|multi|fred|1 MB
hmda_ri|fairness/hmda_2024_RI_muestra.csv|curl|https://ffiec.cfpb.gov/v2/data-browser-api/view/csv?years=2024&states=RI|15 MB
hmda_ca|fairness/hmda_2025_CA.csv|curl|https://ffiec.cfpb.gov/v2/data-browser-api/view/csv?years=2025&states=CA|433 MB
cmf|chile|multi|cmf|580 KB
lending_club|scorecard/lending_club|kagg_d|ethon0426/lending-club-20072020q1|1.7 GB
lending_club_reject|scorecard/lending_club_reject|kagg_d|wordsforthewise/lending-club|3.8 GB
sba|scorecard/sba_national|kagg_d|mirbektoktogaraev/should-this-loan-be-approved-or-denied|172 MB
vehicle|scorecard/vehicle_loan|kagg_d|mamtadhaker/lt-vehicle-loan-default-prediction|59 MB
berka|behavioral/berka|kagg_d|marceloventura/the-berka-dataset|67 MB
fraude|fraude/creditcard_ulb|kagg_d|mlg-ulb/creditcardfraud|144 MB
gmsc|scorecard/give_me_some_credit|kagg_c|GiveMeSomeCredit|6 MB
home_credit|scorecard/home_credit|kagg_c|home-credit-default-risk|689 MB
stability|behavioral/home_credit_stability|kagg_c|home-credit-credit-risk-model-stability|3.2 GB
amex|behavioral/amex|kagg_c|amex-default-prediction|50 GB
freddie|ifrs9/freddiemac|manual|https://claritydownload.fmapps.freddiemac.com/CRT/#/sflld|40 MB por vintage
EOF
)

# El "núcleo": lo que conviene tener siempre. Todo junto pesa ~90 MB.
NUCLEO="hmeq german south_german taiwan credit_approval australian polish taiwan_bank ratings adult lgd mortgage fed fred cmf"

campo() { echo "$REGISTRO" | awk -F'|' -v k="$1" -v n="$2" '$1==k{print $n}'; }
claves() { echo "$REGISTRO" | awk -F'|' '{print $1}'; }

log()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
info() { printf '  \033[33m·\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; }

en_disco() {
  local ruta="$RAW/$1"
  [[ -e "$ruta" ]] && { [[ -f "$ruta" ]] || [[ -n "$(ls -A "$ruta" 2>/dev/null)" ]]; }
}

kaggle_cmd() {
  if command -v kaggle >/dev/null 2>&1; then echo "kaggle"
  elif python3 -c "import kaggle" >/dev/null 2>&1; then echo "python3 -m kaggle"
  else echo ""; fi
}

# ── multi: grupos de archivos que se bajan juntos ───────────────────────────
bajar_multi() {
  local grupo="$1" dir="$RAW/$2"; mkdir -p "$dir"
  case "$grupo" in
    fed)
      local F="https://www.federalreserve.gov/supervisionreg/files"
      for f in 2026_Final_Supervisory_Baseline_Domestic 2026_Final_Supervisory_Baseline_International \
               2026_Final_Supervisory_Severely_Adverse_Domestic 2026_Final_Supervisory_Severely_Adverse_International \
               2026_Final_Historic_Domestic 2026_Final_Historic_International \
               2026_Detailed_Nine_Quarter_Paths public_results_DFAST_2026; do
        curl -fsSL --max-time 120 -o "$dir/fed_$f.csv" "$F/$f.csv" || bad "fed_$f.csv"
      done
      curl -fsSL --max-time 120 -o "$dir/fed_2026_escenarios.pdf" \
        "https://www.federalreserve.gov/publications/files/2026-final-supervisory-stress-test-scenarios-20260204.pdf"
      ;;
    eba_st)
      local S="https://www.eba.europa.eu/assets/st25/full_database/763451"
      for f in TRA_CRE_IRB.csv TRA_CRE_STA.csv TRA_OTH.csv Data_Dictionary.xlsx Metadata_TR.xlsx; do
        curl -fsSL --max-time 600 -o "$dir/eba_st25_$f" "$S/$f" || bad "$f"
      done
      curl -fsSL --max-time 300 -o "$dir/eba_st25_macro_scenario.xlsx" \
        "https://www.eba.europa.eu/sites/default/files/2025-03/d0668400-aed7-40d7-b668-1f77eb24b934/2025%20EU-wide%20stress%20test%20-%20Macro%20financial%20scenario%20%28updated%2026%20February%202025%29-incl%20disclaimer%20for%20EBA%20%285%29.xlsx"
      ;;
    eba_te)
      local T="https://www.eba.europa.eu/assets/TE2025/Full_database/883401"
      for f in tr_cre.csv tr_sov.csv tr_oth.csv tr_mrk.csv TR_Metadata.xlsx SDD.xlsx \
               2025_EU-wide_Transparency_exercise_Mapped_templates.xlsx; do
        curl -fsSL --max-time 600 -o "$dir/eba_$f" "$T/$f" || bad "$f"
      done
      ;;
    fred)
      for s in UNRATE CSUSHPINSA GDPC1 DRSFRMACBS DRCCLACBS DRALACBS FEDFUNDS CPIAUCSL; do
        curl -fsSL --max-time 60 -o "$dir/fred_$s.csv" "https://fred.stlouisfed.org/graph/fredgraph.csv?id=$s" || bad "$s"
      done
      ;;
    cmf)
      local C="https://www.cmfchile.cl/portal/estadisticas/626"
      for p in 111446:2026-05 110807:2026-04 110160:2026-03 109116:2026-02 103972:2026-01 103187:2025-12 \
               102408:2025-11 101097:2025-10 100156:2025-09 99055:2025-08 98093:2025-07 97058:2025-06; do
        curl -fsSL --max-time 90 -o "$dir/cmf_morosidad90_${p##*:}.xlsx" "$C/articles-${p%%:*}_recurso_1.xlsx" || bad "${p##*:}"
      done
      ;;
  esac
}

# ── get ─────────────────────────────────────────────────────────────────────
get_uno() {
  local k="$1"
  local sub met org peso
  sub=$(campo "$k" 2); met=$(campo "$k" 3); org=$(campo "$k" 4); peso=$(campo "$k" 5)
  [[ -z "$sub" ]] && { bad "clave desconocida: $k   (usa: ./descargar.sh ls)"; return 1; }

  if en_disco "$sub"; then info "$k ya está en disco → $sub"; return 0; fi
  printf '  … %s (%s)\n' "$k" "$peso"

  org="${org/UCI\//$UCI/}"; org="${org/CRA\//$CRA/}"

  case "$met" in
    curl)
      mkdir -p "$(dirname "$RAW/$sub")"
      curl -fsSL --max-time 1800 --retry 2 -o "$RAW/$sub" "$org" \
        && ok "$k → raw/$sub ($(du -h "$RAW/$sub" | cut -f1))" || bad "$k"
      ;;
    rar)
      mkdir -p "$(dirname "$RAW/$sub")"
      local tmp="$RAW/$(dirname "$sub")/mortgage_csv.rar"
      curl -fsSL --max-time 600 -o "$tmp" "$org" || { bad "$k"; return 1; }
      (cd "$(dirname "$tmp")" && tar -xf mortgage_csv.rar 2>/dev/null) || \
        { command -v unar >/dev/null && unar -q -o "$(dirname "$tmp")" "$tmp"; }
      rm -f "$tmp"
      [[ -s "$RAW/$sub" ]] && ok "$k → raw/$sub ($(du -h "$RAW/$sub" | cut -f1))" || bad "$k: no se pudo abrir el .rar"
      ;;
    multi) bajar_multi "$org" "$sub" && ok "$k → raw/$sub ($(du -sh "$RAW/$sub" | cut -f1))" ;;
    kagg_d|kagg_c)
      local KG; KG=$(kaggle_cmd)
      [[ -z "$KG" ]] && { bad "kaggle CLI no disponible → pip install kaggle"; return 1; }
      mkdir -p "$RAW/$sub"
      if [[ "$met" == "kagg_d" ]]; then
        $KG datasets download -d "$org" -p "$RAW/$sub" --unzip
      else
        $KG competitions download -c "$org" -p "$RAW/$sub" && \
          (cd "$RAW/$sub" && for z in *.zip; do [[ -f "$z" ]] && unzip -oq "$z" && rm -f "$z"; done)
      fi
      en_disco "$sub" && ok "$k → raw/$sub ($(du -sh "$RAW/$sub" | cut -f1))" \
        || bad "$k — si es competencia, acepta las reglas en kaggle.com/competitions/$org/rules"
      ;;
    manual)
      info "$k requiere navegador con sesión iniciada:  $org"
      info "     ver la sección 'manual' →  ./descargar.sh manual"
      ;;
  esac
}

# ── comandos ────────────────────────────────────────────────────────────────
cmd="${1:-ls}"; shift 2>/dev/null || true

case "$cmd" in
  ls)
    printf '\n\033[1m%-22s %-12s %-10s %s\033[0m\n' CLAVE ESTADO PESO RUTA
    printf '%s\n' "──────────────────────────────────────────────────────────────────────────"
    for k in $(claves); do
      sub=$(campo "$k" 2); peso=$(campo "$k" 5)
      if en_disco "$sub"; then
        real=$(du -sh "$RAW/$sub" 2>/dev/null | cut -f1)
        printf '\033[32m%-22s %-12s\033[0m %-10s %s\n' "$k" "en disco" "${real:-?}" "raw/$sub"
      else
        printf '%-22s \033[90m%-12s\033[0m %-10s %s\n' "$k" "—" "$peso" "raw/$sub"
      fi
    done
    echo; df -h "$BASE" | tail -1 | awk '{print "  disco: "$4" libres de "$2" ("$5" usado)"}'
    ;;

  get)
    [[ $# -eq 0 ]] && { bad "uso: ./descargar.sh get <clave>...  (./descargar.sh ls para verlas)"; exit 1; }
    log "Descargando"
    for k in "$@"; do get_uno "$k"; done
    df -h "$BASE" | tail -1 | awk '{print "\n  disco: "$4" libres ("$5" usado)"}'
    ;;

  rm)
    [[ $# -eq 0 ]] && { bad "uso: ./descargar.sh rm <clave>..."; exit 1; }
    total=0
    for k in "$@"; do
      sub=$(campo "$k" 2)
      [[ -z "$sub" ]] && { bad "clave desconocida: $k"; continue; }
      en_disco "$sub" || { info "$k no está en disco"; continue; }
      printf '  %s → raw/%s (%s)\n' "$k" "$sub" "$(du -sh "$RAW/$sub" | cut -f1)"
      total=$((total+1))
    done
    [[ $total -eq 0 ]] && exit 0
    printf '\nBorrar %d dataset(s)? Se pueden volver a bajar con get. [s/N] ' "$total"
    read -r resp
    if [[ "$resp" =~ ^[sSyY]$ ]]; then
      for k in "$@"; do sub=$(campo "$k" 2); [[ -n "$sub" ]] && rm -rf "${RAW:?}/$sub"; done
      ok "borrados"
      df -h "$BASE" | tail -1 | awk '{print "  disco: "$4" libres ("$5" usado)"}'
    else
      info "cancelado"
    fi
    ;;

  nucleo)
    log "Núcleo permanente (~90 MB): lo que conviene no borrar nunca"
    for k in $NUCLEO; do get_uno "$k"; done
    ;;

  espacio)
    log "Ocupación"
    du -sh "$RAW"/*/* 2>/dev/null | sort -rh | head -15
    printf '\n  total raw/: %s\n' "$(du -sh "$RAW" 2>/dev/null | cut -f1)"
    df -h "$BASE" | tail -1 | awk '{print "  disco:      "$4" libres de "$2" ("$5" usado)"}'
    ;;

  inventario)
    # Regenera INVENTARIO.md con lo que hay en disco ahora mismo.
    OUT="$BASE/INVENTARIO.md"
    {
      echo "# Inventario de \`raw/\`"
      echo
      echo "Generado por \`./descargar.sh inventario\`. Refleja el disco en el momento de correrlo,"
      echo "no el catálogo completo — para eso está \`catalogo.csv\`."
      echo
      printf '**Total:** %s en %s archivos. ' "$(du -sh "$RAW" 2>/dev/null | cut -f1)" "$(find "$RAW" -type f | wc -l | tr -d ' ')"
      df -h "$BASE" | tail -1 | awk '{printf "**Disco:** %s libres de %s (%s usado).\n", $4, $2, $5}'
      echo
      for d in "$RAW"/*/; do
        [[ -d "$d" ]] || continue
        printf '\n## `%s/` — %s\n\n' "$(basename "$d")" "$(du -sh "$d" | cut -f1)"
        echo '```'
        (cd "$d" && for x in *; do
           [[ -e "$x" ]] || continue
           if [[ -d "$x" ]]; then printf '%-42s %8s  (%s archivos)\n' "$x/" "$(du -sh "$x"|cut -f1)" "$(find "$x" -type f|wc -l|tr -d ' ')"
           else printf '%-42s %8s\n' "$x" "$(du -h "$x"|cut -f1)"; fi
         done)
        echo '```'
      done
      echo
      echo "## Ausentes"
      echo
      for k in $(claves); do
        sub=$(campo "$k" 2)
        en_disco "$sub" || printf -- '- `%s` (%s) → `./descargar.sh get %s`\n' "$k" "$(campo "$k" 5)" "$k"
      done
    } > "$OUT"
    ok "INVENTARIO.md regenerado ($(wc -l < "$OUT" | tr -d ' ') líneas)"
    ;;

  manual)
    cat <<'MANUAL'

FUENTES QUE NO SE PUEDEN AUTOMATIZAR
────────────────────────────────────────────────────────────────────────────
Freddie Mac SFLLD   https://claritydownload.fmapps.freddiemac.com/CRT/#/sflld
  Con sesión iniciada. Cada sample_YYYY.zip son 50.000 originaciones + su
  performance mensual (~40 MB). Chrome bloquea descargas múltiples: hay que
  autorizarlas en el ícono de la barra de direcciones. Desde la consola del
  navegador se pueden disparar todas de una:

    Array.from(document.querySelectorAll('.non-full-set-download-link'))
      .filter(e=>/^sample_\d{4}\.zip$/.test(e.textContent.trim()))
      .forEach((e,i)=>setTimeout(()=>e.click(), i*1500))

  Después:  mv ~/Downloads/sample_*.zip raw/ifrs9/freddiemac/

Fannie Mae          https://loanperformancedata.fanniemae.com/lppub/index.html
EFH Chile           https://www.efhweb.cl
S&P transiciones    https://www.spglobal.com/ratings   (matrices en PDF)
MANUAL
    ;;

  *) bad "comando desconocido: $cmd";
     echo "  usa: ls | get <clave> | rm <clave> | nucleo | espacio | manual | inventario" ;;
esac
