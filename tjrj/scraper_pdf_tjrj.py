"""
Scraper para baixar PDFs das sentenças dos processos do TJCE
Baixa apenas os PDFs sem extrair outros dados
"""

import csv
import asyncio
import os
from playwright.async_api import async_playwright
from urllib.parse import unquote, urlparse, parse_qs


def ler_numeros_processos(arquivo_csv="tjrj/data/notebook1/numeros_processos.csv"):
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
        print(f"   Acessando página de consulta...")
        # Navegue para a página inicial
        await page.goto("https://tjrj.pje.jus.br/pje/ConsultaPublica/listView.seam", wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=10000)
        
        # Preencher o campo de busca (campo "Processo")
        print(f"   Preenchendo número do processo...")
        campo_processo = page.get_by_role("textbox", name="Processo", exact=True)
        await campo_processo.click()
        await campo_processo.fill(numero_processo)
        await asyncio.sleep(0.5)
        
        # Clicar no botão Pesquisar
        print(f"   Clicando em Pesquisar...")
        botao_pesquisar = page.get_by_role("button", name="Pesquisar")
        await botao_pesquisar.click()
        
        # Aguardar carregamento da página de resultado
        await page.wait_for_load_state("networkidle", timeout=15000)
        await asyncio.sleep(2)
        
        # Verificar se processo não existe
        try:
            mensagem_erro = page.get_by_text("Não existem informações")
            if await mensagem_erro.is_visible(timeout=2000):
                print("   ✗ Processo não encontrado")
                return False
        except Exception:
            pass
        
        # Clicar no botão "Ver Detalhes" (ícone de link externo)
        print(f"   Procurando botão 'Ver Detalhes'...")
        botao_detalhes = page.locator("a.btn.btn-default.btn-sm[title='Ver Detalhes']")
        if not await botao_detalhes.is_visible(timeout=3000):
            print("   ✗ Botão 'Ver Detalhes' não encontrado")
            return False
        
        print(f"   Clicando em 'Ver Detalhes'...")
        # Capturar popup que abre ao clicar em Ver Detalhes
        async with page.expect_popup(timeout=10000) as popup_info:
            await botao_detalhes.click()
        
        popup = await popup_info.value
        print(f"   ✓ Popup de detalhes aberto")
        
        # Aguardar carregamento do popup
        await popup.wait_for_load_state("networkidle", timeout=15000)
        await asyncio.sleep(2)
        
        # Procurar link do documento (Despacho, Sentença, Decisão)
        print(f"   Procurando link do documento...")
        termos_busca = [
            "Sentença",
            "Decisão",
            "Despacho",
            "Acórdão",
        ]
        
        link_documento = None
        for termo in termos_busca:
            # Procurar link que contenha o termo no texto
            locator = popup.locator(f"a[id*='processoEvento']:has-text('{termo}')")
            if await locator.count() > 0:
                print(f"   ✓ Encontrado link com '{termo}'")
                link_documento = locator.first
                break
        
        if link_documento is None:
            print("   ✗ Link de documento não encontrado")
            await popup.close()
            return False
        
        # Clicar no link do documento (abre outro popup)
        print(f"   Clicando no link do documento...")
        async with popup.expect_popup(timeout=10000) as popup_doc_info:
            await link_documento.click()
        
        popup_doc = await popup_doc_info.value
        print(f"   ✓ Popup do documento aberto")
        
        # Aguardar carregamento
        await popup_doc.wait_for_load_state("networkidle", timeout=15000)
        await asyncio.sleep(2)
        
        # Gerar PDF da página do documento
        print(f"   Gerando PDF da página...")
        os.makedirs("tjrj/data/notebook1/decisoes", exist_ok=True)
        filename = f"tjrj/data/notebook1/decisoes/{numero_processo}.pdf"
        
        await popup_doc.pdf(path=filename, format='A4', print_background=True)
        
        # Verificar se o arquivo foi criado
        if os.path.exists(filename) and os.path.getsize(filename) > 1000:
            file_size = os.path.getsize(filename)
            print(f"   ✓ PDF gerado ({file_size} bytes)")
            
            # Fechar popups
            await popup_doc.close()
            await popup.close()
            return True
        else:
            print(f"   ✗ PDF gerado está vazio ou muito pequeno")
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
    print("SCRAPER TJRJ - Download de PDFs das Sentenças")
    print("=" * 60)
    
    # Ler números dos processos
    print("\n1. Lendo números dos processos...")
    numeros_processos = ler_numeros_processos()
    print(f"   Total de processos: {len(numeros_processos)}")
    
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
        browser = await playwright.chromium.launch(headless=False)  # Mudar para True para rodar sem interface gráfica
        context = await browser.new_context()
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
                    
                    # Aguarde antes da próxima requisição para evitar sobrecarga
                    await asyncio.sleep(1)
                    
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
