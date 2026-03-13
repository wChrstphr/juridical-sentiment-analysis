"""Scraper TJMT para consultar processos e gerar PDF da decisão prioritária."""

import asyncio
import csv
import os
import re
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

URL_CONSULTA = "https://consultaprocessual.tjmt.jus.br/"
TERMOS_DECISAO = ["Sentença", "Julgamento", "Decisão"]

OUTPUT_DIR = "tjmt/data/decisoes"
CSV_PATH = "tjmt/data/notebook1/numeros_processos.csv"

# Site do TJMT pode oscilar por excesso de carga.
# Esses tempos altos reduzem falhas intermitentes.
TIMEOUT_PAGINA_MS = 120000
TIMEOUT_ACAO_MS = 60000
DELAY_ENTRE_PROCESSOS_OK_S = 6
DELAY_ENTRE_PROCESSOS_ERRO_S = 14
DEBUG = False


def ler_numeros_processos(arquivo_csv: str = CSV_PATH) -> list[str]:
    """Lê os números dos processos do arquivo CSV."""
    numeros = []
    with open(arquivo_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            numeros.append(row["numero_processo"])
    return numeros


def validar_numero_cnj(numero: str) -> str:
    """Valida e retorna o número CNJ com 20 dígitos (sem máscara)."""
    n = re.sub(r"\D", "", numero)
    if len(n) != 20:
        raise ValueError(
            f"Número de processo com tamanho inesperado: '{numero}' ({len(n)} dígitos)"
        )
    return n


async def _fechar_modais(page) -> None:
    """Fecha popups/modais de forma tolerante quando existirem."""
    for nome in ["Close", "close", "Fechar", "X"]:
        botao = page.get_by_role("button", name=nome, exact=False).first
        try:
            if await botao.is_visible(timeout=1200):
                await botao.click(timeout=4000)
                await asyncio.sleep(0.8)
        except Exception:
            pass


async def _clicar_ver_processo_completo(page) -> bool:
    """Clica em 'Ver processo completo' com retentativas."""
    for _ in range(4):
        botao = page.get_by_role("button", name=re.compile("Ver processo completo", re.I)).first
        try:
            await botao.wait_for(state="visible", timeout=TIMEOUT_ACAO_MS)
            await botao.click(timeout=TIMEOUT_ACAO_MS)
            await asyncio.sleep(2)
            return True
        except Exception:
            await _fechar_modais(page)
            await asyncio.sleep(2)
    return False


async def _selecionar_documento_prioritario(page):
    """Seleciona o tipo de documento por prioridade (Sentença > Julgamento > Decisão)."""
    for termo in TERMOS_DECISAO:
        doc = page.get_by_text(termo, exact=False).first
        try:
            if await doc.is_visible(timeout=5000):
                texto = (await doc.text_content() or "").strip()
                await doc.click(timeout=TIMEOUT_ACAO_MS)
                return texto or termo
        except Exception:
            continue
    return None


async def baixar_pdf_processo(
    page,
    numero_processo: str,
    cache_existentes: set,
    max_retries: int = 5,
) -> bool:
    """
    Baixa o PDF da decisão do processo via consulta processual do TJMT.

    Fluxo de navegação:
        1. Busca o processo no portal público
        2. Abre popup de detalhes do processo (page1)
        3. Localiza o link da decisão na seção "Documentos juntados ao processo"
        4. Abre popup do visualizador do documento (page2)
        5. Clica no botão de download e salva o arquivo

    Retorna True em caso de sucesso, False caso contrário.
    """
    numero_cnj = validar_numero_cnj(numero_processo)
    filename = os.path.join(OUTPUT_DIR, f"{numero_processo}.pdf")

    if numero_processo in cache_existentes:
        print("   PDF já existe, pulando...")
        return True

    for tentativa in range(1, max_retries + 1):
        try:
            # 1) Entrar na consulta
            await page.goto(
                URL_CONSULTA,
                wait_until="domcontentloaded",
                timeout=TIMEOUT_PAGINA_MS,
            )
            await page.wait_for_load_state("networkidle", timeout=TIMEOUT_PAGINA_MS)
            await asyncio.sleep(2)

            # 2) Preencher processo (site aceita sem máscara)
            campo_processo = page.locator("span:has-text('Número do Processo') input").first
            try:
                await campo_processo.wait_for(state="visible", timeout=12000)
            except PlaywrightTimeoutError:
                campo_processo = page.get_by_role("textbox").first
                await campo_processo.wait_for(state="visible", timeout=TIMEOUT_ACAO_MS)

            await campo_processo.click(timeout=TIMEOUT_ACAO_MS)
            await campo_processo.fill(numero_cnj, timeout=TIMEOUT_ACAO_MS)
            await asyncio.sleep(1.5)

            await page.get_by_role("button", name=re.compile("Consultar", re.I)).first.click(
                timeout=TIMEOUT_ACAO_MS
            )
            await page.wait_for_load_state("networkidle", timeout=TIMEOUT_PAGINA_MS)
            await asyncio.sleep(4)

            # Verificar se nenhum resultado foi encontrado
            try:
                sem_resultado = page.get_by_text("Nenhum processo encontrado", exact=False)
                if await sem_resultado.is_visible(timeout=3500):
                    print("   Processo não encontrado na consulta")
                    return False
            except Exception:
                pass

            # 3) Abrir visão completa
            entrou = await _clicar_ver_processo_completo(page)
            if not entrou:
                print("   Não foi possível abrir 'Ver processo completo'")
                return False

            await page.wait_for_load_state("domcontentloaded", timeout=TIMEOUT_PAGINA_MS)
            await asyncio.sleep(3)

            # --- DEBUG opcional ---
            if DEBUG:
                print("\n   [DEBUG] Textos visíveis na tela atual:")
                todos_links = await page.locator("a,button,span").all()
                for i, a in enumerate(todos_links):
                    try:
                        texto = (await a.text_content() or "").strip()
                        visivel = await a.is_visible()
                        if texto and visivel:
                            print(f"     [{i:03d}] texto='{texto[:90]}'")
                    except Exception:
                        pass

            # 4) Abrir lista de PDFs/documentos
            botao_pdf = page.locator(".far.fa-file-pdf, .fa-file-pdf").first
            await botao_pdf.wait_for(state="visible", timeout=TIMEOUT_ACAO_MS)
            await botao_pdf.click(timeout=TIMEOUT_ACAO_MS)
            await asyncio.sleep(2)

            # 5) Selecionar decisão por prioridade
            paginas_antes = set(page.context.pages)
            documento_escolhido = await _selecionar_documento_prioritario(page)
            if not documento_escolhido:
                print("   Documento de decisão não encontrado (Sentença/Julgamento/Decisão)")
                return False

            print(f"   Documento selecionado: {documento_escolhido}")

            pagina_pdf = page
            try:
                nova_pagina = await page.context.wait_for_event("page", timeout=12000)
                if nova_pagina not in paginas_antes:
                    pagina_pdf = nova_pagina
            except Exception:
                pagina_pdf = page

            await pagina_pdf.wait_for_load_state("domcontentloaded", timeout=TIMEOUT_PAGINA_MS)
            await asyncio.sleep(4)

            # 6) Gerar PDF da visualização atual
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            pdf_bytes = await pagina_pdf.pdf(
                print_background=True,
                width="210mm",
                height="297mm",
                margin={
                    "top": "10mm",
                    "bottom": "10mm",
                    "left": "10mm",
                    "right": "10mm",
                },
            )
            with open(filename, "wb") as f:
                f.write(pdf_bytes)

            if pagina_pdf is not page:
                try:
                    await pagina_pdf.close()
                except Exception:
                    pass

            cache_existentes.add(numero_processo)
            print(f"   PDF gerado ({len(pdf_bytes):,} bytes)")
            return True

        except Exception as e:
            erro_msg = str(e)
            if "closed" in erro_msg.lower():
                raise
            if tentativa < max_retries:
                espera = tentativa * 10
                print(
                    f"   Erro (tentativa {tentativa}/{max_retries}): {erro_msg[:120]} — aguardando {espera}s..."
                )
                await asyncio.sleep(espera)
            else:
                print(f"   Erro após {max_retries} tentativas: {erro_msg[:120]}")
                return False

    return False


async def executar_scraping():
    """Executa o download dos PDFs para todos os processos do CSV."""
    print("=" * 60)
    print("SCRAPER TJMT (Consulta Processual) - Download de PDFs das Decisões")
    print("=" * 60)

    print("\n1. Lendo números dos processos...")
    numeros_processos = ler_numeros_processos()
    print(f"   Total de processos: {len(numeros_processos)}")

    print("\n2. Iniciando download dos PDFs...")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    cache_existentes = {
        f[:-4] for f in os.listdir(OUTPUT_DIR) if f.endswith(".pdf")
    }
    print(f"   PDFs já baixados (cache): {len(cache_existentes)}")
    restantes = len(numeros_processos) - sum(
        1 for n in numeros_processos if n in cache_existentes
    )
    print(f"   Restantes               : {restantes}")

    async with async_playwright() as playwright:
        sucessos = 0
        falhas = 0
        erros_consecutivos = 0

        async def criar_browser():
            browser = await playwright.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1920, "height": 1080},
                ignore_https_errors=True,
            )
            await ctx.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
            pg = await ctx.new_page()
            return browser, ctx, pg

        browser, context, page = await criar_browser()

        try:
            for idx, numero in enumerate(numeros_processos, 1):
                # Reiniciar browser periodicamente para reduzir instabilidade.
                if idx > 1 and idx % 30 == 0:
                    print(f"\n>>> Reiniciando browser (processo {idx})...")
                    try:
                        await context.close()
                        await browser.close()
                    except Exception:
                        pass
                    await asyncio.sleep(8)
                    browser, context, page = await criar_browser()
                    print(">>> Browser reiniciado!")

                try:
                    numero_cnj = validar_numero_cnj(numero)
                except ValueError as e:
                    print(f"\n[{idx}/{len(numeros_processos)}] IGNORADO — {e}")
                    falhas += 1
                    continue

                print(f"\n[{idx}/{len(numeros_processos)}] {numero_cnj}")

                try:
                    sucesso = await baixar_pdf_processo(page, numero, cache_existentes)

                    if sucesso:
                        sucessos += 1
                        erros_consecutivos = 0
                    else:
                        falhas += 1
                        erros_consecutivos += 1

                    # Delay adaptativo
                    if erros_consecutivos > 3:
                        delay = DELAY_ENTRE_PROCESSOS_ERRO_S
                        print(
                            f"   (Aguardando {delay}s — erros consecutivos: {erros_consecutivos})"
                        )
                    elif erros_consecutivos > 0:
                        delay = max(8, DELAY_ENTRE_PROCESSOS_OK_S)
                    else:
                        delay = DELAY_ENTRE_PROCESSOS_OK_S
                    await asyncio.sleep(delay)

                except Exception as e:
                    if "closed" in str(e).lower():
                        print("\nBrowser foi fechado manualmente — encerrando.")
                        break
                    falhas += 1
                    erros_consecutivos += 1
                    print(f"   Erro inesperado: {str(e)}")

        finally:
            try:
                await context.close()
                await browser.close()
            except Exception:
                pass

    # Resumo final
    total = len(numeros_processos)
    print("\n" + "=" * 60)
    print("ESTATÍSTICAS FINAIS")
    print("=" * 60)
    print(f"Total de processos : {total}")
    print(
        f"Sucessos           : {sucessos} ({sucessos * 100 // total if total else 0}%)"
    )
    print(f"Falhas             : {falhas} ({falhas * 100 // total if total else 0}%)")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(executar_scraping())
