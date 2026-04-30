"""
Scraper para baixar PDFs das sentenças dos processos do TJAL
Baixa apenas os PDFs sem extrair outros dados
"""

import csv
import asyncio
import os
from playwright.async_api import async_playwright
from urllib.parse import unquote, urlparse, parse_qs


def ler_numeros_processos(arquivo_csv="tjam/data/notebook1/numeros_processos.csv"):
    """Lê os números dos processos do arquivo CSV"""
    numeros = []
    with open(arquivo_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            numeros.append(row["numero_processo"])
    return numeros


async def baixar_pdf_processo(page, numero_processo, browser, max_retries=3):
    """
    Baixa o PDF da sentença do processo.
    
    Args:
        page: Página do Playwright
        numero_processo: Número do processo
        browser: Instância do browser
        max_retries: Número máximo de tentativas em caso de timeout
    
    Retorna: bool indicando sucesso do download
    """
    # Verificar se arquivo já existe
    filename = f"tjam/data/notebook1/decisoes/{numero_processo}.pdf"
    if os.path.exists(filename):
        print("   PDF já existe, pulando...")
        return True
    
    try:
        # Navegue para a página inicial com retry
        for tentativa in range(max_retries):
            try:
                await page.goto("https://consultasaj.tjam.jus.br/cpopg/open.do", wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_load_state("networkidle", timeout=20000)
                break
            except Exception as e:
                if tentativa < max_retries - 1:
                    wait_time = (tentativa + 1) * 3
                    print(f"   Timeout (tentativa {tentativa + 1}/{max_retries}), aguardando {wait_time}s...")
                    await asyncio.sleep(wait_time)
                else:
                    print(f"   Erro ao carregar página após {max_retries} tentativas")
                    return False
        
        # Selecionar opção "Outros"
        try:
            radio_outros = page.get_by_role("radio", name="Outros")
            await radio_outros.check(timeout=10000)
            await asyncio.sleep(0.3)
        except Exception as e:
            print(f"   Erro ao selecionar radio 'Outros': {e}")
            return False
        
        # Preencher o campo de busca
        campo_busca = page.get_by_role("textbox", name="Número do processo")
        await campo_busca.click()
        await campo_busca.fill(numero_processo)
        
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
            "contains(normalize-space(text()), 'Julgad')",   # Julgado/Julgada
            "contains(normalize-space(text()), 'Decis')",    # Decisão/Decisao
            "contains(normalize-space(text()), 'Senten')",   # Sentença/Sentenca
            "contains(normalize-space(text()), 'Procedente')",
            "contains(normalize-space(text()), 'Improcedente')",
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
        
        # Obter URL relativa do link
        url_relativa = await link.first.get_attribute("href")
        
        # CORREÇÃO: Usar o domínio www2.tjam.jus.br em vez de esaj.tjam.jus.br
        # O link é relativo e deve ser resolvido no contexto do domínio não-bloqueado
        url_completa = "https://consultasaj.tjam.jus.br" + url_relativa
        
        # Navegar para a página do documento
        await page.goto(url_completa, wait_until="domcontentloaded")
        await asyncio.sleep(2)
        
        # Aguardar iframe
        try:
            await page.wait_for_selector("iframe", timeout=5000)
        except Exception:
            print("   Iframe não encontrado")
            return False
        
        # Extrair URL do PDF do iframe
        iframe = page.locator("iframe")
        if not await iframe.is_visible(timeout=3000):
            print("   Iframe não visível")
            return False
        
        viewer_url = await iframe.get_attribute("src")
        
        # Extrair caminho real do PDF do parâmetro file=
        parsed = urlparse(viewer_url)
        params = parse_qs(parsed.query)
        
        if "file" not in params:
            print("   Parâmetro 'file' não encontrado")
            return False
        
        pdf_path = unquote(params["file"][0])
        
        # CORREÇÃO: Usar www2.tjam.jus.br para download do PDF também
        pdf_url = "https://consultasaj.tjam.jus.br" + pdf_path
        
        # Baixar PDF
        os.makedirs("tjam/data/notebook1/decisoes", exist_ok=True)
        context = browser.contexts[0]
        
        try:
            response = await context.request.get(pdf_url, timeout=30000)
            
            if response.ok:
                pdf_bytes = await response.body()
                with open(filename, "wb") as f:
                    f.write(pdf_bytes)
                print(f"    PDF baixado ({len(pdf_bytes)} bytes)")
                return True
            else:
                print(f"     Erro HTTP {response.status}")
                return False
        except Exception as e:
            print(f"   Erro ao baixar PDF: {e}")
            return False
        
    except Exception as e:
        if "closed" in str(e).lower():
            raise
        print(f"   Erro: {str(e)}")
        return False


async def executar_scraping():
    """Executa o download dos PDFs"""
    print("=" * 60)
    print("SCRAPER TJAL - Download de PDFs das Sentenças")
    print("=" * 60)
    
    # Ler números dos processos
    print("\n1. Lendo números dos processos...")
    numeros_processos = ler_numeros_processos()
    print(f"   Total de processos: {len(numeros_processos)}")
    
    # Iniciar scraping
    print("\n2. Iniciando download dos PDFs...")
    
    async with async_playwright() as playwright:
        sucessos = 0
        falhas = 0
        erros_consecutivos = 0
        
        # Função para criar browser
        async def criar_browser():
            browser = await playwright.chromium.launch(
                headless=True,
                args=['--disable-blink-features=AutomationControlled', '--no-sandbox']
            )
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                viewport={'width': 1920, 'height': 1080},
                ignore_https_errors=True
            )
            await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
            page = await context.new_page()
            return browser, context, page
        
        browser, context, page = await criar_browser()
        
        try:
            for idx, numero in enumerate(numeros_processos, 1):
                # Reiniciar browser a cada 50 processos para evitar problemas
                if idx > 1 and idx % 50 == 0:
                    print(f"\n>>> Reiniciando browser (processo {idx})...")
                    try:
                        await context.close()
                        await browser.close()
                    except:
                        pass
                    await asyncio.sleep(5)
                    browser, context, page = await criar_browser()
                    print(">>> Browser reiniciado!")
                
                print(f"\n[{idx}/{len(numeros_processos)}]")
                print(f"Processando {numero}...")
                
                try:
                    sucesso = await baixar_pdf_processo(page, numero, browser)
                    
                    if sucesso:
                        sucessos += 1
                        erros_consecutivos = 0
                    else:
                        falhas += 1
                        erros_consecutivos += 1
                    
                    # Delay adaptativo baseado em erros consecutivos
                    if erros_consecutivos > 3:
                        delay = 5
                        print(f"   (Aguardando {delay}s devido a erros consecutivos)")
                    elif erros_consecutivos > 0:
                        delay = 2
                    else:
                        delay = 1
                    
                    await asyncio.sleep(delay)
                    
                except Exception as e:
                    if "closed" in str(e).lower():
                        print("\nBrowser foi fechado")
                        break
                    falhas += 1
                    erros_consecutivos += 1
                    print(f"   Erro: {str(e)}")
        
        finally:
            try:
                await context.close()
                await browser.close()
            except Exception:
                pass
    
    # Estatísticas
    total = len(numeros_processos)
    print("\n" + "=" * 60)
    print("RELATÓRIO FINAL")
    print("=" * 60)
    print(f"Total de processos: {total}")
    print(f"Sucessos: {sucessos} ({sucessos*100//total if total > 0 else 0}%)")
    print(f"Falhas: {falhas} ({falhas*100//total if total > 0 else 0}%)")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(executar_scraping())
