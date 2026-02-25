"""
Scraper para baixar PDFs das sentenças dos processos do TJRS
Baixa apenas os PDFs sem extrair outros dados
"""

import csv
import asyncio
import os
import time
import re
from playwright.async_api import async_playwright
from urllib.parse import unquote, urlparse, parse_qs


def ler_numeros_processos(arquivo_csv="tjrs/data/notebook1/numeros_processos.csv"):
    """Lê os números dos processos do arquivo CSV"""
    numeros = []
    with open(arquivo_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            numeros.append(row["numero_processo"])
    return numeros


async def baixar_pdf_processo(page, numero_processo, browser):
    """
    Baixa o PDF da sentença do processo do TJRS.
    
    Args:
        page: Página do Playwright
        numero_processo: Número do processo
        browser: Instância do browser
    
    Retorna: bool indicando sucesso do download
    """
    try:
        print(f"   Acessando URL de busca...")
        # Navegar para a página de consulta processual do TJRS
        await page.goto("https://consulta.tjrs.jus.br/consulta-processual/", wait_until="domcontentloaded", timeout=30000)
        
        # Aguardar o Angular carregar
        print(f"   Aguardando carregamento da página...")
        await page.wait_for_load_state("networkidle", timeout=20000)
        await asyncio.sleep(2)
        
        print(f"   ✓ Página carregada")
        
        # Preencher formulário de busca (SEM IFRAME - direto na página)
        print(f"   Preenchendo formulário de busca...")
        try:
            campo_numero = page.get_by_role("textbox", name="Número Processo")
            await campo_numero.click()
            await campo_numero.fill(numero_processo)
            await asyncio.sleep(0.5)
            
            botao_pesquisar = page.get_by_role("button", name="Pesquisar")
            await botao_pesquisar.click()
            
            print(f"   Aguardando resultado da pesquisa...")
            await page.wait_for_load_state("networkidle", timeout=15000)
            await asyncio.sleep(2)
        except Exception as e:
            print(f"   ✗ Erro ao preencher formulário: {str(e)[:50]}")
            return False
        
        # Expandir movimentações
        print(f"   Procurando por movimentações...")
        try:
            ver_todas = page.get_by_role("link", name="Ver todas as movimentações/")
            if await ver_todas.is_visible(timeout=3000):
                print(f"   Expandindo movimentações...")
                await ver_todas.click()
                await asyncio.sleep(1.5)
            else:
                raise Exception("Link não visível, tentar alternativas")
        except Exception as e:
            # Tentar clicar diretamente no elemento
            print(f"   Tentando método alternativo para expandir...")
            try:
                ver_todas_alt = page.locator("text=Ver todas as movimentações")
                if await ver_todas_alt.count() > 0:
                    await ver_todas_alt.first.click()
                    await asyncio.sleep(3)
                    print(f"   ✓ Movimentações expandidas (método alternativo)")
            except:
                print(f"   Botão 'Ver todas' não encontrado")
        
        # Aumentar itens por página
        print(f"   Aumentando itens por página...")
        try:
            # Clicar no dropdown de itens por página
            combobox = page.get_by_role("combobox", name="Itens por página:")
            await combobox.locator("svg").click()
            await asyncio.sleep(1)
            
            # Selecionar 50 itens - tentar por role primeiro
            try:
                opcao_50 = page.get_by_role("option", name="50")
                if await opcao_50.is_visible(timeout=3000):
                    await opcao_50.click()
                    await asyncio.sleep(2.5)
                    print(f"   ✓ Expandido para 50 itens por página")
            except:
                # Tentar clicar usando get_by_text como alternativa
                opcao_50_alt = page.locator("mat-option").filter(has_text="50")
                if await opcao_50_alt.count() > 0:
                    await opcao_50_alt.first.click()
                    await asyncio.sleep(2.5)
                    print(f"   ✓ Expandido para 50 itens por página (método alternativo)")
        except Exception as e:
            print(f"   Não foi possível expandir itens por página: {str(e)[:50]}")
        
        # Procurar por links de documentos na tabela de movimentações
        print(f"   Procurando links de documentos...")
        
        termos_busca = [
            "Julgado",
            "Sentença", 
            "Decisão",
            "Acórdão",
        ]
        
        pdf_baixado = False
        
        for termo in termos_busca:
            if pdf_baixado:
                break
                
            try:
                # Buscar linhas (rows) que contenham o termo
                rows = page.get_by_role("row")
                count = await rows.count()
                
                print(f"   Verificando {count} linhas para '{termo}'...")
                
                for i in range(count):
                    try:
                        row = rows.nth(i)
                        texto_row = await row.inner_text()
                        
                        # Verificar se a linha contém o termo (case insensitive)
                        if termo.lower() in texto_row.lower():
                            print(f"   ✓ Encontrado '{termo}' na linha {i}")
                            
                            # Procurar link na linha
                            link = row.get_by_role("link")
                            if await link.count() > 0:
                                print(f"   Tentando clicar no link...")
                                
                                # Capturar popup
                                try:
                                    async with page.expect_popup(timeout=8000) as popup_info:
                                        await link.first.click()
                                    
                                    popup = await popup_info.value
                                    print(f"   ✓ Popup aberto: {popup.url[:80]}...")
                                    
                                    # Aguardar carregar
                                    await popup.wait_for_load_state("networkidle", timeout=10000)
                                    await asyncio.sleep(2)
                                    
                                    # Clicar no conteúdo para carregar o PDF
                                    try:
                                        content = popup.locator("#Content")
                                        if await content.is_visible(timeout=3000):
                                            print(f"   Clicando no conteúdo (#Content)...")
                                            await content.click()
                                            await asyncio.sleep(2)
                                            print(f"   ✓ Conteúdo carregado")
                                    except Exception as e_content:
                                        print(f"   Erro ao clicar no conteúdo: {str(e_content)[:50]}")
                                    
                                    # Verificar se popup ainda está aberta
                                    if popup.is_closed():
                                        print(f"   ✗ Popup foi fechada prematuramente")
                                        continue
                                    
                                    # Tentar baixar o PDF da URL da popup
                                    popup_url = popup.url
                                    print(f"   URL do popup: {popup_url[:100]}")
                                    
                                    if ".pdf" in popup_url.lower() or "pdf" in popup_url.lower():
                                        print(f"   Baixando PDF da URL...")
                                        context = browser.contexts[0]
                                        
                                        try:
                                            response = await context.request.get(popup_url, timeout=15000)
                                            
                                            if response.ok:
                                                pdf_bytes = await response.body()
                                                
                                                # Verificar se é realmente um PDF
                                                if pdf_bytes[:4] == b'%PDF':
                                                    os.makedirs("tjrs/data/notebook1/decisoes", exist_ok=True)
                                                    filename = f"tjrs/data/notebook1/decisoes/{numero_processo}.pdf"
                                                    with open(filename, "wb") as f:
                                                        f.write(pdf_bytes)
                                                    print(f"   ✓ PDF baixado ({len(pdf_bytes)} bytes)")
                                                    await popup.close()
                                                    pdf_baixado = True
                                                    return True
                                                else:
                                                    print(f"   ✗ Resposta não é um PDF válido")
                                        except Exception as e_req:
                                            print(f"   Erro ao baixar: {str(e_req)[:50]}")
                                    
                                    # Gerar PDF da página do popup
                                    print(f"   Gerando PDF da página...")
                                    try:
                                        os.makedirs("tjrs/data/notebook1/decisoes", exist_ok=True)
                                        filename = f"tjrs/data/notebook1/decisoes/{numero_processo}.pdf"
                                        
                                        # Aguardar um pouco mais antes de gerar o PDF
                                        await asyncio.sleep(1)
                                        
                                        # Gerar PDF da página do popup
                                        await popup.pdf(path=filename, format='A4', print_background=True)
                                        
                                        # Verificar se o arquivo foi criado e tem conteúdo
                                        if os.path.exists(filename) and os.path.getsize(filename) > 1000:
                                            file_size = os.path.getsize(filename)
                                            print(f"   ✓ PDF gerado da página ({file_size} bytes)")
                                            await popup.close()
                                            pdf_baixado = True
                                            return True
                                        else:
                                            print(f"   ✗ PDF gerado está vazio ou muito pequeno")
                                            if os.path.exists(filename):
                                                os.remove(filename)
                                    except Exception as e_pdf:
                                        print(f"   Erro ao gerar PDF: {str(e_pdf)[:80]}")
                                    
                                    # Fechar popup apenas se ainda estiver aberta
                                    try:
                                        if not popup.is_closed():
                                            await popup.close()
                                    except:
                                        pass
                                    
                                except Exception as e_popup:
                                    print(f"   Erro no popup: {str(e_popup)[:80]}")
                                    
                    except Exception as e_row:
                        continue
                        
            except Exception as e:
                print(f"   Erro ao buscar '{termo}': {str(e)[:50]}")
                continue
        
        if not pdf_baixado:
            print("   ✗ Nenhum PDF encontrado")
        
        return pdf_baixado
        
    except Exception as e:
        if "closed" in str(e).lower():
            raise
        print(f"   ✗ Erro: {str(e)}")
        return False


async def executar_scraping():
    """Executa o download dos PDFs"""
    print("="*60)
    print("SCRAPER TJRS - Download de PDFs das Sentenças")
    print("="*60)
    
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
        browser = await playwright.chromium.launch(headless=True)  # Mudar para True para rodar sem interface gráfica
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
    print("ESTATÍSTICAS")
    print("=" * 60)
    print(f"Total de processos: {len(numeros_processos)}")
    print(f"Sucessos: {sucessos} ({sucessos*100//len(numeros_processos) if len(numeros_processos) > 0 else 0}%)")
    print(f"Falhas: {falhas} ({falhas*100//len(numeros_processos) if len(numeros_processos) > 0 else 0}%)")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(executar_scraping())
