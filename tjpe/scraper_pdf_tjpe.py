"""
Scraper para baixar PDFs das sentenças dos processos do TJPE (PJe)
Baixa apenas os PDFs sem extrair outros dados
"""

import csv
import asyncio
import os
from playwright.async_api import async_playwright


NON_INTERACTIVE = os.getenv("SCRAPER_NON_INTERACTIVE", "0") == "1"


def aguardar_confirmacao_captcha(mensagem):
    """Aguarda resolução manual do CAPTCHA; em modo não interativo apenas sinaliza."""
    if NON_INTERACTIVE:
        print("CAPTCHA_REQUIRED: execução não interativa detectou desafio de verificação humana")
        return False
    try:
        input(mensagem)
        return True
    except EOFError:
        print("CAPTCHA_REQUIRED: entrada padrão indisponível para resolução manual")
        return False


def ler_numeros_processos(arquivo_csv="tjpe/data/notebook1/numeros_processos.csv"):
    """Lê os números dos processos do arquivo CSV"""
    numeros = []
    with open(arquivo_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            numeros.append(row["numero_processo"])
    return numeros


async def baixar_pdf_processo(page, numero_processo, browser):
    """
    Baixa o PDF da sentença do processo do TJPE.
    
    Args:
        page: Página do Playwright
        numero_processo: Número do processo
        browser: Instância do browser
    
    Retorna: bool indicando sucesso do download
    """
    try:
        print(f"   Acessando página de consulta...")
        # Navegar para a página do PJe TJPE
        await page.goto("https://pje.cloud.tjpe.jus.br/1g/ConsultaPublica/listView.seam", wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=10000)
        await asyncio.sleep(1)
        
        # Verificar se apareceu verificação de robô/CAPTCHA logo na entrada
        try:
            # Verificar mensagem "Vamos confirmar que você é humano"
            mensagem_humano = page.locator("h1:has-text('Vamos confirmar que você é humano')")
            if await mensagem_humano.count() > 0:
                print("\n" + "!"*60)
                print("⚠️  VERIFICAÇÃO DE ROBÔ DETECTADA NA ENTRADA!")
                print("⚠️  Mensagem: 'Vamos confirmar que você é humano'")
                print("!"*60)
                print("Por favor, resolva o CAPTCHA manualmente no navegador.")
                print("Após resolver, pressione ENTER aqui para continuar...")
                print("!"*60 + "\n")
                if not aguardar_confirmacao_captcha(""):
                    return False
                print("   ✓ Continuando...")
                await asyncio.sleep(2)
            
            # Verificar também iframes de CAPTCHA
            captcha_iframe = page.locator("iframe[src*='recaptcha'], iframe[src*='hcaptcha'], iframe[title*='reCAPTCHA']")
            if await captcha_iframe.count() > 0:
                print("\n" + "!"*60)
                print("⚠️  VERIFICAÇÃO DE ROBÔ DETECTADA NA ENTRADA!")
                print("!"*60)
                print("Por favor, resolva o CAPTCHA manualmente no navegador.")
                print("Após resolver, pressione ENTER aqui para continuar...")
                print("!"*60 + "\n")
                if not aguardar_confirmacao_captcha(""):
                    return False
                print("   ✓ Continuando...")
                await asyncio.sleep(2)
        except Exception:
            pass
        
        # Preencher o campo do número do processo
        print(f"   Preenchendo número do processo...")
        campo_processo = page.locator("#fPP\\:numProcesso-inputNumeroProcessoDecoration\\:numProcesso-inputNumeroProcesso")
        
        # Aguardar o campo estar pronto com timeout maior
        try:
            await campo_processo.wait_for(state="visible", timeout=60000)
        except Exception:
            print("   ⚠️  Campo demorou para aparecer, pode ter CAPTCHA...")
            print("\n" + "!"*60)
            print("⚠️  POSSÍVEL VERIFICAÇÃO DE ROBÔ!")
            print("!"*60)
            print("Verifique se há CAPTCHA no navegador.")
            print("Após resolver (se houver), pressione ENTER para continuar...")
            print("!"*60 + "\n")
            if not aguardar_confirmacao_captcha(""):
                return False
            print("   ✓ Tentando continuar...")
            await asyncio.sleep(2)
            await campo_processo.wait_for(state="visible", timeout=30000)
        
        await campo_processo.click(timeout=30000)
        await campo_processo.fill(numero_processo)
        await asyncio.sleep(0.5)
        
        # Clicar no botão Pesquisar
        print(f"   Clicando em Pesquisar...")
        botao_pesquisar = page.locator("#fPP\\:searchProcessos")
        await botao_pesquisar.click()
        
        # Aguardar resultado
        await page.wait_for_load_state("networkidle", timeout=15000)
        await asyncio.sleep(2)
        
        # Verificar se apareceu verificação de robô/CAPTCHA
        try:
            # Verificar mensagem "Vamos confirmar que você é humano"
            mensagem_humano = page.locator("h1:has-text('Vamos confirmar que você é humano')")
            if await mensagem_humano.count() > 0:
                print("\n" + "!"*60)
                print("⚠️  VERIFICAÇÃO DE ROBÔ DETECTADA!")
                print("⚠️  Mensagem: 'Vamos confirmar que você é humano'")
                print("!"*60)
                print("Por favor, resolva o CAPTCHA manualmente no navegador.")
                print("Após resolver, pressione ENTER aqui para continuar...")
                print("!"*60 + "\n")
                if not aguardar_confirmacao_captcha(""):
                    return False
                print("   ✓ Continuando...")
                await asyncio.sleep(2)
            
            # Procurar por elementos comuns de verificação (reCAPTCHA, hCaptcha, etc)
            captcha_iframe = page.locator("iframe[src*='recaptcha'], iframe[src*='hcaptcha'], iframe[title*='reCAPTCHA']")
            if await captcha_iframe.count() > 0:
                print("\n" + "!"*60)
                print("⚠️  VERIFICAÇÃO DE ROBÔ DETECTADA!")
                print("!"*60)
                print("Por favor, resolva o CAPTCHA manualmente no navegador.")
                print("Após resolver, pressione ENTER aqui para continuar...")
                print("!"*60 + "\n")
                if not aguardar_confirmacao_captcha(""):
                    return False
                print("   ✓ Continuando...")
                await asyncio.sleep(2)
        except Exception:
            pass
        
        # Verificar se processo não existe
        try:
            mensagem_erro = page.get_by_text("Não existem informações", exact=False)
            if await mensagem_erro.is_visible(timeout=2000):
                print("   ✗ Processo não encontrado")
                return False
        except Exception:
            pass
        
        # Clicar no botão "Ver Detalhes"
        print(f"   Clicando em Ver Detalhes...")
        botao_detalhes = page.locator("a.btn.btn-default.btn-sm[title='Ver Detalhes']").first
        if not await botao_detalhes.is_visible(timeout=3000):
            print("   ✗ Botão 'Ver Detalhes' não encontrado")
            return False
        
        # Capturar popup de detalhes
        async with page.expect_popup(timeout=10000) as popup_info:
            await botao_detalhes.click()
        
        popup = await popup_info.value
        print(f"   ✓ Popup de detalhes aberto")
        
        # Aguardar carregamento do popup
        await popup.wait_for_load_state("networkidle", timeout=15000)
        await asyncio.sleep(2)
        
        # Procurar link do documento (Sentença)
        print(f"   Procurando link do documento...")
        # Buscar por link que contém "Sentença"
        link_documento = popup.locator("a.btn.btn-default.btn-sm:has-text('Sentença')").first
        
        if await link_documento.count() == 0:
            # Tentar buscar por "Decisão" se não encontrar Sentença
            link_documento = popup.locator("a.btn.btn-default.btn-sm:has-text('Decisão')").first
        
        if await link_documento.count() == 0:
            print("   ✗ Link de documento não encontrado")
            await popup.close()
            return False
        
        if not await link_documento.is_visible(timeout=2000):
            print("   ✗ Link de documento não visível")
            await popup.close()
            return False
        
        print(f"   ✓ Link de documento encontrado")
        
        # Capturar popup do documento
        print(f"   Clicando no link do documento...")
        async with popup.expect_popup(timeout=10000) as popup_doc_info:
            await link_documento.click()
        
        popup_doc = await popup_doc_info.value
        print(f"   ✓ Popup do documento aberto")
        
        # Aguardar carregamento do documento
        await popup_doc.wait_for_load_state("networkidle", timeout=15000)
        await asyncio.sleep(2)
        
        # Gerar PDF da página do documento
        print(f"   Gerando PDF...")
        os.makedirs("tjpe/data/notebook1/decisoes", exist_ok=True)
        filename = f"tjpe/data/notebook1/decisoes/{numero_processo}.pdf"
        
        await popup_doc.pdf(path=filename, format='A4', print_background=True)
        
        # Verificar se o arquivo foi criado
        if os.path.exists(filename) and os.path.getsize(filename) > 1000:
            file_size = os.path.getsize(filename)
            print(f"   ✓ PDF gerado ({file_size} bytes)")
            await popup_doc.close()
            await popup.close()
            return True
        else:
            print(f"   ✗ PDF inválido ou muito pequeno")
            if os.path.exists(filename):
                os.remove(filename)
            await popup_doc.close()
            await popup.close()
            return False
        
    except Exception as e:
        if "closed" in str(e).lower():
            raise
        print(f"   ✗ Erro: {str(e)[:100]}")
        return False


async def executar_scraping():
    """Executa o download dos PDFs"""
    print("=" * 60)
    print("SCRAPER TJPE - Download de PDFs das Sentenças")
    print("=" * 60)
    
    # Ler números dos processos
    print("\n1. Lendo números dos processos...")
    numeros_processos = ler_numeros_processos()
    print(f"   Total de processos: {len(numeros_processos)}")
    
    # Verificar quantos já foram baixados
    os.makedirs("tjpe/data/notebook1/decisoes", exist_ok=True)
    processos_baixados = set()
    for arquivo in os.listdir("tjpe/data/notebook1/decisoes"):
        if arquivo.endswith(".pdf"):
            processo = arquivo.replace(".pdf", "")
            processos_baixados.add(processo)
    
    print(f"   Processos já baixados: {len(processos_baixados)}")
    
    # Perguntar se quer continuar de onde parou
    if len(processos_baixados) > 0:
        print("\n   Deseja continuar de onde parou? (s/n):")
        try:
            continuar = input("   Resposta: ").strip().lower()
            if continuar == 's':
                numeros_processos = [n for n in numeros_processos if n not in processos_baixados]
                print(f"   ✓ Continuando... Restam {len(numeros_processos)} processos")
        except:
            pass
    
    # Perguntar de qual processo iniciar (para pular até um específico)
    print("\n   Quer pular até um processo específico? Digite o número (Enter para começar do primeiro):")
    try:
        processo_inicio = input("   Processo: ").strip()
        if processo_inicio and processo_inicio in numeros_processos:
            idx_inicio = numeros_processos.index(processo_inicio)
            processos_pulados = idx_inicio
            numeros_processos = numeros_processos[idx_inicio:]
            print(f"   ✓ Pulando {processos_pulados} processo(s)... Começando de: {processo_inicio}")
            print(f"   Restam {len(numeros_processos)} processos")
        elif processo_inicio:
            print(f"   ⚠️  Processo não encontrado na lista ou já foi baixado")
    except:
        pass
    
    # Perguntar quantos processar (para teste)
    print("\n   Digite quantos processos testar (Enter para todos):")
    try:
        limite_input = input("   Limite: ").strip()
        if limite_input:
            limite = int(limite_input)
            numeros_processos = numeros_processos[:limite]
            print(f"   Testando apenas {limite} processo(s)")
    except:
        pass
    
    # Iniciar scraping
    print("\n2. Iniciando download dos PDFs...")
    
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=False,
            timeout=60000,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--disable-gpu'
            ]
        )
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 720},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = await context.new_page()
        
        sucessos = 0
        falhas = 0
        
        try:
            for idx, numero in enumerate(numeros_processos, 1):
                print(f"\n{'='*50}")
                print(f"[{idx}/{len(numeros_processos)}] Processo: {numero}")
                print('='*50)
                
                try:
                    sucesso = await baixar_pdf_processo(page, numero, browser)
                    
                    if sucesso:
                        sucessos += 1
                    else:
                        falhas += 1
                    
                    # Aguardar tempo entre requisições
                    await asyncio.sleep(2)
                    
                except Exception as e:
                    if "closed" in str(e).lower():
                        print("\nBrowser foi fechado")
                        break
                    falhas += 1
                    print(f"   ✗ Erro: {str(e)}")
        
        finally:
            try:
                await context.close()
                await browser.close()
            except Exception:
                pass
    
    # Estatísticas
    print("\n" + "=" * 60)
    print("RELATÓRIO FINAL")
    print("=" * 60)
    print(f"Total de processos: {len(numeros_processos)}")
    print(f"Sucessos: {sucessos} ({sucessos*100//len(numeros_processos) if len(numeros_processos) > 0 else 0}%)")
    print(f"Falhas: {falhas} ({falhas*100//len(numeros_processos) if len(numeros_processos) > 0 else 0}%)")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(executar_scraping())
