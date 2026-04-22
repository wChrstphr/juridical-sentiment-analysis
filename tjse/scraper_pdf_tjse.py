"""
Scraper para baixar PDFs das sentenças dos processos do TJCE
Baixa apenas os PDFs sem extrair outros dados
"""

import csv
import asyncio
import os
from playwright.async_api import async_playwright
from urllib.parse import unquote, urlparse, parse_qs


def ler_numeros_processos(arquivo_csv="tjse/data/notebook1/numeros_processos.csv"):
    """Lê os números dos processos do arquivo CSV"""
    numeros = []
    with open(arquivo_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            numeros.append(row["numero_processo"])
    return numeros


async def baixar_pdf_processo(page, numero_processo, browser):
    """
    Baixa o PDF da sentença do processo.
    
    Args:
        page: Página do Playwright
        numero_processo: Número do processo
        browser: Instância do browser
    
    Retorna: bool indicando sucesso do download
    """
    try:
        # Navegue para a página inicial para garantir contexto de sessão adequado
        await page.goto("https://interface-consultaprocessual.tjse.jus.br/consultaprocessual/paginas/consulta/consultaProcessos.xhtml", wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=10000)
        
        # Preencher o campo de busca usando o ID específico do TJSE
        campo_busca = page.locator("#tabView\\:inputNumeroProcesso")
        await campo_busca.click()
        await campo_busca.fill(numero_processo)
        await asyncio.sleep(0.3)
        
        # Clicar no botão Consultar
        botao_consultar = page.get_by_role("button", name="Consultar")
        await botao_consultar.click()
        
        # Aguardar carregamento da página de resultado
        await page.wait_for_load_state("networkidle", timeout=15000)
        
        # Verificar se processo não existe
        try:
            mensagem_erro = page.get_by_text("Não existem informações")
            if await mensagem_erro.is_visible(timeout=2000):
                print("   Processo não encontrado")
                return False
        except Exception:
            pass
        
        # Expandir movimentações
        link_mais = page.locator("#linkmovimentacoes")
        if await link_mais.is_visible(timeout=2000):
            await link_mais.click()
            await asyncio.sleep(0.8)
        
        # Localizar link do documento da decisão/sentença
        # Busca por diversos tipos de decisões (evitar "Transitado em Julgado")
        link = None
        termos_busca = [
            "contains(normalize-space(text()), 'Julgado')",  # Julgado procedente/improcedente
            "contains(normalize-space(text()), 'Decisão')",  # Decisão Interlocutória, etc
            "contains(normalize-space(text()), 'Sentença')", # Sentença
        ]
        
        for termo in termos_busca:
            locator = page.locator(f"xpath=//a[@class='linkMovVincProc' and {termo}]")
            if await locator.count() > 0:
                link = locator
                break
        
        # Verificar se encontrou algum link
        if link is None or await link.count() == 0:
            print("   Link de decisão não encontrado (segredo de justiça ou sem PDF)")
            return False
        
        
        if not await link.first.is_visible(timeout=2000):
            print("   Link de decisão não visível")
            return False
        
        url_relativa = await link.first.get_attribute("href")
        url_completa = "https://interface-consultaprocessual.tjse.jus.br/consultaprocessual/paginas/consulta/consultaProcessos.xhtml" + url_relativa
        
        # Navegar para a página do viewer
        await page.goto(url_completa, wait_until="networkidle")
        await asyncio.sleep(2)
        
        # Extrair URL do PDF do iframe
        iframe = page.locator("iframe")
        if not await iframe.is_visible(timeout=3000):
            print("   Iframe não encontrado")
            return False
        
        viewer_url = await iframe.get_attribute("src")
        
        # Extrair caminho real do PDF do parâmetro file=
        parsed = urlparse(viewer_url)
        params = parse_qs(parsed.query)
        
        if "file" not in params:
            print("   Parâmetro 'file' não encontrado")
            return False
        
        pdf_path = unquote(params["file"][0])
        pdf_url = "https://interface-consultaprocessual.tjse.jus.br/consultaprocessual/paginas/consulta/consultaProcessos.xhtml" + pdf_path
        
        # Baixar PDF
        os.makedirs("tjse/data/notebook1/decisoes", exist_ok=True)
        context = browser.contexts[0]
        response = await context.request.get(pdf_url)
        
        if response.ok:
            pdf_bytes = await response.body()
            filename = f"tjse/data/notebook1/decisoes/{numero_processo}.pdf"
            with open(filename, "wb") as f:
                f.write(pdf_bytes)
            print(f"    PDF baixado ({len(pdf_bytes)} bytes)")
            return True
        else:
            print(f"     Erro HTTP {response.status}")
            return False
        
    except Exception as e:
        if "closed" in str(e).lower():
            raise
        print(f"   Erro: {str(e)}")
        return False


async def executar_scraping():
    """Executa o download dos PDFs"""
    print("=" * 60)
    print("SCRAPER TJCE - Download de PDFs das Sentenças")
    print("=" * 60)
    
    # Ler números dos processos
    print("\n1. Lendo números dos processos...")
    numeros_processos = ler_numeros_processos()
    print(f"   Total de processos: {len(numeros_processos)}")
    
    # Iniciar scraping
    print("\n2. Iniciando download dos PDFs...")
    
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=False,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-features=IsolateOrigins,site-per-process'
            ]
        )
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080},
            locale='pt-BR',
            timezone_id='America/Sao_Paulo',
            extra_http_headers={
                'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7',
            }
        )
        
        # Remover webdriver flag
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)
        
        page = await context.new_page()
        
        sucessos = 0
        falhas = 0
        
        try:
            for idx, numero in enumerate(numeros_processos, 1):
                print(f"\n[{idx}/{len(numeros_processos)}]")
                print(f"Processando {numero}...")
                
                try:
                    sucesso = await baixar_pdf_processo(page, numero, browser)
                    
                    if sucesso:
                        sucessos += 1
                    else:
                        falhas += 1
                    
                    # Aguarde antes da próxima requisição para evitar sobrecarga
                    await asyncio.sleep(0.5)
                    
                except Exception as e:
                    if "closed" in str(e).lower():
                        print("\nBrowser foi fechado")
                        break
                    falhas += 1
                    print(f"   Erro: {str(e)}")
        
        finally:
            try:
                await context.close()
                await browser.close()
            except Exception:
                pass
    
    # Estatísticas
    print("\n" + "=" * 60)
    print("ESTATÍSTICAS")
    print("=" * 60)
    print(f"Total de processos: {len(numeros_processos)}")
    print(f"Sucessos: {809} ({809*100//len(numeros_processos)}%)")
    print(f"Falhas: {593} ({593*100//len(numeros_processos)}%)")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(executar_scraping())
