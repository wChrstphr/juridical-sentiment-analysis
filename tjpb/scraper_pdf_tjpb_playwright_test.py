"""
Scraper TJPB com Playwright - TESTE
Para você testar e me devolver funcionando
"""

import csv
import asyncio
import os
from playwright.async_api import async_playwright


def ler_numeros_processos(arquivo_csv="tjpb/data/notebook1/numeros_processos.csv"):
    """Lê os números dos processos do arquivo CSV"""
    numeros = []
    with open(arquivo_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            numeros.append(row["numero_processo"])
    return numeros[:3]  # Apenas 3 processos para teste


async def baixar_pdf_processo(page, numero_processo):
    """Baixa o PDF da sentença do processo do TJPB"""
    try:
        print(f"   Acessando página de consulta...")
        await page.goto("https://consultapublica.tjpb.jus.br/pje/ConsultaPublica/listView.seam", wait_until="domcontentloaded")
        await page.wait_for_load_state("networkidle", timeout=10000)
        await asyncio.sleep(1)
        
        # Preencher o campo do número do processo
        print(f"   Preenchendo número do processo: {numero_processo}...")
        campo_processo = page.locator("#fPP\\:numProcesso-inputNumeroProcessoDecoration\\:numProcesso-inputNumeroProcesso")
        await campo_processo.wait_for(state="visible", timeout=30000)
        await campo_processo.click()
        await campo_processo.fill(numero_processo)
        await asyncio.sleep(0.5)
        
        # Clicar no botão Pesquisar
        print(f"   Clicando em Pesquisar...")
        botao_pesquisar = page.locator("#fPP\\:searchProcessos")
        await botao_pesquisar.click()
        
        # Aguardar resultado
        await page.wait_for_load_state("networkidle", timeout=15000)
        await asyncio.sleep(2)
        
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
        
        # AQUI É ONDE VOCÊ PRECISA TESTAR E CORRIGIR!
        # Procurar link do documento (Sentença ou Decisão)
        print(f"   Procurando link do documento...")
        
        # Tentar diferentes formas de encontrar o link
        # Tente essas opções e me diga qual funcionou:
        
        # OPÇÃO 1: Como no TJPE
        link_documento = popup.locator("a.btn.btn-default.btn-sm:has-text('Sentença')").first
        
        if await link_documento.count() == 0:
            # OPÇÃO 2: Buscar por "Decisão"
            link_documento = popup.locator("a.btn.btn-default.btn-sm:has-text('Decisão')").first
        
        if await link_documento.count() == 0:
            # OPÇÃO 3: Qualquer link que tenha essas palavras
            link_documento = popup.locator("a:has-text('Sentença'), a:has-text('Decisão')").first
        
        if await link_documento.count() == 0:
            # OPÇÃO 4: Link com ícone de documento
            link_documento = popup.locator("a[title*='documento'], a[title*='Sentença'], a[title*='Decisão']").first
        
        # SE NENHUMA FUNCIONAR, ADICIONE AQUI A SUA SOLUÇÃO:
        # link_documento = popup.locator("SEU_SELETOR_AQUI").first
        
        if await link_documento.count() == 0:
            print("   ✗ Link de documento não encontrado")
            print("   DEBUG: Veja a página manualmente e me diga como encontrar o link!")
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
        os.makedirs("tjpb/data/notebook1/decisoes_teste", exist_ok=True)
        filename = f"tjpb/data/notebook1/decisoes_teste/{numero_processo}.pdf"
        
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
        print(f"   ✗ Erro: {str(e)[:200]}")
        return False


async def main():
    print("="*60)
    print("TESTE PLAYWRIGHT - TJPB")
    print("="*60)
    
    numeros = ler_numeros_processos()
    print(f"Testando {len(numeros)} processos...")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()
        
        for idx, numero in enumerate(numeros, 1):
            print(f"\n[{idx}/{len(numeros)}] Processo: {numero}")
            print("="*50)
            
            sucesso = await baixar_pdf_processo(page, numero)
            
            if sucesso:
                print("✓ SUCESSO!")
            else:
                print("✗ FALHA")
            
            await asyncio.sleep(2)
        
        await browser.close()
    
    print("\n" + "="*60)
    print("TESTE FINALIZADO")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
