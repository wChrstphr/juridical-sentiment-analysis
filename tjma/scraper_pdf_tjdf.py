"""
Scraper para baixar PDFs das decisões dos processos do TJDF via PJE
Utiliza Playwright para navegar no portal de consulta pública do PJE-TJDF
"""

import csv
import asyncio
import os
from playwright.async_api import async_playwright

URL_CONSULTA = "https://pje.tjma.jus.br/pje/ConsultaPublica/listView.seam"

# Termos de decisão buscados em ordem de prioridade.
# Os links reais têm formato: "DD/MM/YYYY HH:MM:SS - NomeDoc (Categoria)"
# Sentença/Julgamento têm precedência pois representam decisões finais.
TERMOS_DECISAO = ["SENTENÇA (SENTENÇA)", "JULGAMENTO (JULGAMENTO)", "DECISÃO (DECISÃO)"]

OUTPUT_DIR = "tjma/data/decisoes"
CSV_PATH = "tjma/data/notebook1/numeros_processos.csv"

# Ativar para imprimir todos os links visíveis de page1 (sem pausar o browser)
DEBUG = False


def ler_numeros_processos(arquivo_csv: str = CSV_PATH) -> list[str]:
    """Lê os números dos processos do arquivo CSV."""
    numeros = []
    with open(arquivo_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            numeros.append(row["numero_processo"])
    return numeros


def formatar_numero_cnj(numero: str) -> str:
    """
    Converte número de processo de 20 dígitos para o formato CNJ.

    Exemplo:
        '07550892120258070001' -> '0755089-21.2025.8.07.0001'

    Formato CNJ: NNNNNNN-DD.AAAA.J.TT.OOOO
        N[0:7]  - número sequencial
        N[7:9]  - dígito verificador
        N[9:13] - ano
        N[13]   - segmento da justiça
        N[14:16]- tribunal
        N[16:20]- origem (vara/zona)
    """
    n = numero.strip()
    if len(n) != 20:
        raise ValueError(
            f"Número de processo com tamanho inesperado: '{n}' ({len(n)} dígitos)"
        )
    return f"{n[0:7]}-{n[7:9]}.{n[9:13]}.{n[13]}.{n[14:16]}.{n[16:20]}"


async def baixar_pdf_processo(page, numero_processo: str, max_retries: int = 3) -> bool:
    """
    Baixa o PDF da decisão do processo via PJE-TJDF.

    Fluxo de navegação:
        1. Busca o processo no portal público
        2. Abre popup de detalhes do processo (page1)
        3. Localiza o link da decisão na seção "Documentos juntados ao processo"
        4. Abre popup do visualizador do documento (page2)
        5. Clica no botão de download e salva o arquivo

    Retorna True em caso de sucesso, False caso contrário.
    """
    numero_cnj = formatar_numero_cnj(numero_processo)
    filename = os.path.join(OUTPUT_DIR, f"{numero_processo}.pdf")

    if os.path.exists(filename):
        print("   PDF já existe, pulando...")
        return True

    for tentativa in range(1, max_retries + 1):
        page1 = None
        page2 = None
        try:
            # 1. Navegar para a página de busca
            await page.goto(URL_CONSULTA, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_load_state("networkidle", timeout=20000)

            # 2. Preencher número do processo e pesquisar
            campo_processo = page.get_by_role("textbox", name="Processo", exact=True)
            await campo_processo.click()
            await campo_processo.fill(numero_cnj)

            await page.get_by_role("button", name="Pesquisar").click()
            await page.wait_for_load_state("networkidle", timeout=15000)

            # Verificar se nenhum resultado foi encontrado
            try:
                sem_resultado = page.get_by_text("Nenhum processo encontrado")
                if await sem_resultado.is_visible(timeout=2000):
                    print("   Processo não encontrado na consulta")
                    return False
            except Exception:
                pass

            # 3. Abrir popup de detalhes do processo
            async with page.expect_popup(timeout=15000) as page1_info:
                await page.get_by_role("link", name="Ver detalhes do processo").click()
            page1 = await page1_info.value
            await page1.wait_for_load_state("domcontentloaded", timeout=20000)
            await page1.wait_for_load_state("networkidle", timeout=20000)

            # 4. Encontrar link de decisão na seção de documentos

            # --- DEBUG: listar todos os links visíveis em page1 ---
            if DEBUG:
                print("\n   [DEBUG] Links visíveis em page1 (excluindo sem texto):")
                todos_links = await page1.locator("a").all()
                for i, a in enumerate(todos_links):
                    try:
                        texto = (await a.text_content() or "").strip()
                        href = await a.get_attribute("href") or ""
                        visivel = await a.is_visible()
                        if texto and visivel:
                            print(
                                f"     [{i:03d}] texto='{texto[:90]}' href='{href[:70]}'"
                            )
                    except Exception:
                        pass

            # Helper de tradução para XPath case-insensitive com acentos
            _UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZÁÉÍÓÚÃÕÂÊÎÔÛÀÈÌÒÙÇ"
            _LOWER = "abcdefghijklmnopqrstuvwxyzáéíóúãõâêîôûàèìòùç"

            def _xpath_link(termo: str) -> str:
                """
                XPath que encontra <a> cujo texto descendente contenha `termo`
                (case-insensitive) E que NÃO comece por "visualizar"
                (filtrando os links-container "Visualizar documentos...").
                """
                return (
                    f"xpath=.//a["
                    f"contains("
                    f"translate(normalize-space(string(.)),'{_UPPER}','{_LOWER}'),"
                    f"'{termo}'"
                    f") and not("
                    f"starts-with("
                    f"translate(normalize-space(string(.)),'{_UPPER}','{_LOWER}'),"
                    f"'visualizar'"
                    f"))"
                    f"]"
                )

            # Prioridade: Sentença (decisão final) > Julgamento > Decisão (interlocutória)
            link_decisao = None
            for termo in TERMOS_DECISAO:
                locator = page1.locator(_xpath_link(termo)).first
                try:
                    count = await locator.count()
                    visivel = (
                        await locator.is_visible(timeout=2000) if count > 0 else False
                    )
                except Exception:
                    count, visivel = 0, False

                if count > 0 and visivel:
                    link_decisao = locator
                    texto_real = (await locator.text_content() or "").strip()
                    href_real = await locator.get_attribute("href") or ""
                    print(
                        f"   Documento encontrado: '{texto_real[:80]}' href='{href_real[:60]}'"
                    )
                    break

            if link_decisao is None:
                print(
                    "   Link de decisão não encontrado (segredo de justiça ou sem documento)"
                )
                if page1:
                    await page1.close()
                return False

            # 5. Abrir popup do visualizador do documento
            async with page1.expect_popup(timeout=15000) as page2_info:
                await link_decisao.click()
            page2 = await page2_info.value
            await page2.wait_for_load_state("domcontentloaded", timeout=20000)

            # 6. Gerar PDF via page.pdf() — o botão "Gerar PDF" do servidor
            # exige autenticação. Usamos a impressora interna do Chromium que
            # converte o HTML já renderizado em PDF sem nenhum POST ao servidor.
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            pdf_bytes = await page2.pdf(
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
            print(f"   PDF gerado ({len(pdf_bytes):,} bytes)")
            return True

        except Exception as e:
            erro_msg = str(e)
            if "closed" in erro_msg.lower():
                raise
            if tentativa < max_retries:
                espera = tentativa * 4
                print(
                    f"   Erro (tentativa {tentativa}/{max_retries}): {erro_msg[:80]} — aguardando {espera}s..."
                )
                await asyncio.sleep(espera)
            else:
                print(f"   Erro após {max_retries} tentativas: {erro_msg[:120]}")
                return False
        finally:
            for popup in [page2, page1]:
                if popup:
                    try:
                        await popup.close()
                    except Exception:
                        pass

    return False


async def executar_scraping():
    """Executa o download dos PDFs para todos os processos do CSV."""
    print("=" * 60)
    print("SCRAPER TJDF (PJE) - Download de PDFs das Decisões")
    print("=" * 60)

    print("\n1. Lendo números dos processos...")
    numeros_processos = ler_numeros_processos()
    print(f"   Total de processos: {len(numeros_processos)}")

    print("\n2. Iniciando download dos PDFs...")

    async with async_playwright() as playwright:
        sucessos = 0
        falhas = 0
        erros_consecutivos = 0

        async def criar_browser():
            browser = await playwright.chromium.launch(
                headless=True,
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
                # Reiniciar browser a cada 50 processos para evitar vazamento de memória
                if idx > 1 and idx % 50 == 0:
                    print(f"\n>>> Reiniciando browser (processo {idx})...")
                    try:
                        await context.close()
                        await browser.close()
                    except Exception:
                        pass
                    await asyncio.sleep(5)
                    browser, context, page = await criar_browser()
                    print(">>> Browser reiniciado!")

                try:
                    numero_cnj = formatar_numero_cnj(numero)
                except ValueError as e:
                    print(f"\n[{idx}/{len(numeros_processos)}] IGNORADO — {e}")
                    falhas += 1
                    continue

                print(f"\n[{idx}/{len(numeros_processos)}] {numero_cnj}")

                try:
                    sucesso = await baixar_pdf_processo(page, numero)

                    if sucesso:
                        sucessos += 1
                        erros_consecutivos = 0
                    else:
                        falhas += 1
                        erros_consecutivos += 1

                    # Delay adaptativo
                    if erros_consecutivos > 3:
                        delay = 5
                        print(
                            f"   (Aguardando {delay}s — erros consecutivos: {erros_consecutivos})"
                        )
                    elif erros_consecutivos > 0:
                        delay = 2
                    else:
                        delay = 1
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
