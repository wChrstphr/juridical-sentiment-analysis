"""
Scraper para baixar PDFs das sentenças dos processos do TJPB (PJe)
Baixa apenas os PDFs sem extrair outros dados
"""

import csv
import time
import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium_stealth import stealth


NON_INTERACTIVE = os.getenv("SCRAPER_NON_INTERACTIVE", "0") == "1"


def aguardar_confirmacao_usuario(mensagem, motivo_captcha=False):
    """Aguarda interação do usuário quando necessário; em modo não interativo não bloqueia."""
    if NON_INTERACTIVE:
        if motivo_captcha:
            print("CAPTCHA_REQUIRED: execução não interativa detectou desafio de verificação humana")
        return False
    try:
        input(mensagem)
        return True
    except EOFError:
        if motivo_captcha:
            print("CAPTCHA_REQUIRED: entrada padrão indisponível para resolução manual")
        return False


def ler_numeros_processos(arquivo_csv="tjpb/data/notebook1/numeros_processos.csv"):
    """Lê os números dos processos do arquivo CSV"""
    numeros = []
    with open(arquivo_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            numeros.append(row["numero_processo"])
    return numeros


def criar_driver():
    """Cria e configura um novo driver"""
    options = webdriver.ChromeOptions()
    options.add_argument('--start-maximized')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    
    stealth(driver,
            languages=["pt-BR", "pt"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
            )
    return driver


def baixar_pdf_processo(driver, numero_processo, primeiro_acesso=False):
    """
    Baixa o PDF da sentença do processo do TJPB.
    
    Args:
        driver: WebDriver do Selenium
        numero_processo: Número do processo
        primeiro_acesso: Se True, pausa para resolver Cloudflare
    
    Retorna: bool indicando sucesso do download
    """
    try:
        print(f"   Acessando página de consulta...")
        # Navegar para a página do PJe TJPB
        driver.get("https://consultapublica.tjpb.jus.br/pje/ConsultaPublica/listView.seam")
        
        # Pausar APENAS no primeiro acesso para resolver Cloudflare
        if primeiro_acesso:
            print("\n" + "!"*60)
            print("⚠️  PRIMEIRO ACESSO - RESOLVA O CLOUDFLARE")
            print("!"*60)
            print("1. Aguarde o Cloudflare aparecer no navegador")
            print("2. Clique no checkbox 'Confirme que é humano'")
            print("3. AGUARDE a página de consulta carregar completamente")
            print("4. Pressione ENTER aqui para continuar")
            print("")
            print("IMPORTANTE: Após resolver no primeiro processo,")
            print("os próximos geralmente não pedem verificação.")
            print("!"*60 + "\n")
            if not aguardar_confirmacao_usuario(
                "Pressione ENTER após resolver o Cloudflare e ver a página de consulta...",
                motivo_captcha=True,
            ):
                return False
            print("   ✓ Continuando...")
            time.sleep(3)
        else:
            # Nos processos seguintes, apenas aguardar carregar
            time.sleep(2)
        
        # Aguardar o campo do número do processo estar visível
        print(f"   Preenchendo número do processo...")
        wait = WebDriverWait(driver, 30)
        
        try:
            campo_processo = wait.until(
                EC.presence_of_element_located((By.ID, "fPP:numProcesso-inputNumeroProcessoDecoration:numProcesso-inputNumeroProcesso"))
            )
        except TimeoutException:
            print("   ⚠️  Campo demorou para aparecer...")
            print("\n" + "!"*60)
            print("⚠️  POSSÍVEL VERIFICAÇÃO DE ROBÔ!")
            print("!"*60)
            print("Verifique se há CAPTCHA no navegador.")
            print("Após resolver (se houver), pressione ENTER para continuar...")
            print("!"*60 + "\n")
            if not aguardar_confirmacao_usuario("", motivo_captcha=True):
                return False
            print("   ✓ Tentando continuar...")
            time.sleep(2)
            campo_processo = driver.find_element(By.ID, "fPP:numProcesso-inputNumeroProcessoDecoration:numProcesso-inputNumeroProcesso")
        
        # Usar JavaScript para preencher o campo (evita problemas com máscara)
        print(f"   Inserindo: {numero_processo}")
        driver.execute_script(f"arguments[0].value = '{numero_processo}';", campo_processo)
        
        # Disparar eventos para garantir que o campo seja reconhecido
        driver.execute_script("""
            var event = new Event('input', { bubbles: true });
            arguments[0].dispatchEvent(event);
            var changeEvent = new Event('change', { bubbles: true });
            arguments[0].dispatchEvent(changeEvent);
        """, campo_processo)
        
        time.sleep(1)
        
        # Clicar no botão Pesquisar
        print(f"   Clicando em Pesquisar...")
        botao_pesquisar = driver.find_element(By.ID, "fPP:searchProcessos")
        botao_pesquisar.click()
        
        # Aguardar resultado
        time.sleep(3)
        
        # Verificar se processo não existe
        try:
            mensagem_erro = driver.find_element(By.XPATH, "//*[contains(text(), 'Não existem informações')]")
            if mensagem_erro.is_displayed():
                print("   ✗ Processo não encontrado")
                return False
        except NoSuchElementException:
            pass
        
        # Clicar no botão "Ver Detalhes"
        print(f"   Clicando em Ver Detalhes...")
        try:
            # Tentar múltiplos seletores
            botao_detalhes = None
            try:
                botao_detalhes = wait.until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "a.btn.btn-default.btn-sm[title='Ver Detalhes']"))
                )
            except TimeoutException:
                # Tentar sem o title
                try:
                    botao_detalhes = driver.find_element(By.XPATH, "//a[contains(@class, 'btn') and contains(text(), 'Ver Detalhes')]")
                except NoSuchElementException:
                    # Tentar com partial text
                    botao_detalhes = driver.find_element(By.PARTIAL_LINK_TEXT, "Ver Detalhes")
            
            if not botao_detalhes or not botao_detalhes.is_displayed():
                print("   ✗ Botão 'Ver Detalhes' não encontrado ou não visível")
                return False
        except (TimeoutException, NoSuchElementException) as e:
            print(f"   ✗ Botão 'Ver Detalhes' não encontrado: {str(e)[:50]}")
            return False
        
        # Pegar as janelas antes de clicar
        janelas_antes = driver.window_handles
        botao_detalhes.click()
        time.sleep(2)
        
        # Aguardar nova janela (popup de detalhes)
        wait.until(lambda d: len(d.window_handles) > len(janelas_antes))
        janelas_depois = driver.window_handles
        popup_detalhes = [j for j in janelas_depois if j not in janelas_antes][0]
        driver.switch_to.window(popup_detalhes)
        print(f"   ✓ Popup de detalhes aberto")
        
        # Aguardar carregamento do popup
        time.sleep(3)
        
        # Procurar link do documento (Sentença ou Decisão)
        print(f"   Procurando link do documento...")
        
        # Verificar se há documentos disponíveis
        try:
            sem_resultados = driver.find_elements(By.XPATH, "//*[contains(text(), '0 resultados') or contains(text(), 'Nenhum registro')]")
            if sem_resultados:
                for elem in sem_resultados:
                    if elem.is_displayed():
                        print("   ✗ Processo sem documentos disponíveis (0 resultados)")
                        driver.close()
                        driver.switch_to.window(janelas_antes[0])
                        return False
        except Exception:
            pass
        
        link_documento = None
        
        # Tentativa 1: Buscar por "VISUALIZAR" (padrão TJPB)
        try:
            link_documento = driver.find_element(By.XPATH, "//a[contains(@class, 'btn') and contains(., 'VISUALIZAR')]")
        except NoSuchElementException:
            pass
        
        # Tentativa 2: Buscar por "Sentença"
        if not link_documento:
            try:
                link_documento = driver.find_element(By.XPATH, "//a[contains(@class, 'btn') and contains(., 'Sentença')]")
            except NoSuchElementException:
                pass
        
        # Tentativa 3: Buscar por "Decisão"
        if not link_documento:
            try:
                link_documento = driver.find_element(By.XPATH, "//a[contains(@class, 'btn') and contains(., 'Decisão')]")
            except NoSuchElementException:
                pass
        
        # Tentativa 4: Buscar por "SENTENÇA" (maiúscula)
        if not link_documento:
            try:
                link_documento = driver.find_element(By.XPATH, "//a[contains(@class, 'btn') and contains(., 'SENTENÇA')]")
            except NoSuchElementException:
                pass
        
        # Tentativa 5: Buscar por "DECISÃO" (maiúscula)
        if not link_documento:
            try:
                link_documento = driver.find_element(By.XPATH, "//a[contains(@class, 'btn') and contains(., 'DECISÃO')]")
            except NoSuchElementException:
                pass
        
        # Tentativa 6: Qualquer link com btn-sm que contenha data (padrão: "28/11/2025")
        if not link_documento:
            try:
                links_botoes = driver.find_elements(By.CSS_SELECTOR, "a.btn.btn-sm")
                for link in links_botoes:
                    texto = link.text
                    # Verificar se contém data no formato dd/mm/yyyy
                    if "/" in texto and any(char.isdigit() for char in texto):
                        link_documento = link
                        break
            except:
                pass
        
        # Tentativa 7: Primeiro link com classe btn-sm
        if not link_documento:
            try:
                link_documento = driver.find_element(By.CSS_SELECTOR, "a.btn.btn-sm")
            except NoSuchElementException:
                pass
        
        if not link_documento:
            print("   ✗ Link de documento não encontrado")
            print(f"   DEBUG: HTML da página salvo para análise")
            # Salvar HTML para debug
            try:
                with open(f"tjpb/debug_{numero_processo}.html", "w", encoding="utf-8") as f:
                    f.write(driver.page_source)
            except:
                pass
            driver.close()
            driver.switch_to.window(janelas_antes[0])
            return False
        
        # Verificar se está visível
        try:
            if not link_documento.is_displayed():
                print("   ✗ Link de documento não visível")
                driver.close()
                driver.switch_to.window(janelas_antes[0])
                return False
        except Exception:
            print("   ✗ Erro ao verificar visibilidade do link")
            driver.close()
            driver.switch_to.window(janelas_antes[0])
            return False
        
        print(f"   ✓ Link de documento encontrado: {link_documento.text}")
        
        # Clicar no link do documento
        print(f"   Clicando no link do documento...")
        janelas_antes_doc = driver.window_handles
        link_documento.click()
        time.sleep(2)
        
        # Aguardar nova janela (popup do documento)
        wait.until(lambda d: len(d.window_handles) > len(janelas_antes_doc))
        janelas_depois_doc = driver.window_handles
        popup_documento = [j for j in janelas_depois_doc if j not in janelas_antes_doc][0]
        driver.switch_to.window(popup_documento)
        print(f"   ✓ Popup do documento aberto")
        
        time.sleep(3)
        
        # Salvar como PDF usando print
        print(f"   Gerando PDF...")
        os.makedirs("tjpb/data/notebook1/decisoes", exist_ok=True)
        filename = f"tjpb/data/notebook1/decisoes/{numero_processo}.pdf"
        
        # Usar JavaScript para imprimir para PDF
        print_options = {
            'paperWidth': 8.27,  # A4
            'paperHeight': 11.69,
            'printBackground': True
        }
        
        # Executar impressão
        result = driver.execute_cdp_cmd("Page.printToPDF", print_options)
        
        import base64
        with open(filename, 'wb') as f:
            f.write(base64.b64decode(result['data']))
        
        # Verificar se o arquivo foi criado
        if os.path.exists(filename) and os.path.getsize(filename) > 1000:
            file_size = os.path.getsize(filename)
            print(f"   ✓ PDF gerado ({file_size} bytes)")
            
            # Fechar popups e voltar para janela principal
            driver.close()
            driver.switch_to.window(popup_detalhes)
            driver.close()
            driver.switch_to.window(janelas_antes[0])
            return True
        else:
            print(f"   ✗ PDF inválido ou muito pequeno")
            if os.path.exists(filename):
                os.remove(filename)
            
            # Fechar popups e voltar para janela principal
            driver.close()
            driver.switch_to.window(popup_detalhes)
            driver.close()
            driver.switch_to.window(janelas_antes[0])
            return False
        
    except Exception as e:
        print(f"   ✗ Erro: {str(e)[:100]}")
        # Tentar voltar para janela principal
        try:
            driver.switch_to.window(driver.window_handles[0])
        except:
            pass
        return False


def executar_scraping():
    """Executa o download dos PDFs"""
    print("=" * 60)
    print("SCRAPER TJPB - Download de PDFs das Sentenças")
    print("=" * 60)
    
    # Ler números dos processos
    print("\n1. Lendo números dos processos...")
    numeros_processos = ler_numeros_processos()
    print(f"   Total de processos: {len(numeros_processos)}")
    
    # Verificar quantos já foram baixados
    os.makedirs("tjpb/data/notebook1/decisoes", exist_ok=True)
    processos_baixados = set()
    for arquivo in os.listdir("tjpb/data/notebook1/decisoes"):
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
    print("   Iniciando navegador (Chrome com Stealth)...")
    
    driver = criar_driver()
    
    sucessos = 0
    falhas = 0
    precisa_cloudflare = True  # Controla se precisa resolver Cloudflare
    
    try:
        for idx, numero in enumerate(numeros_processos, 1):
            print(f"\n{'='*50}")
            print(f"[{idx}/{len(numeros_processos)}] Processo: {numero}")
            print('='*50)
            
            tentar_novamente = True
            while tentar_novamente:
                try:
                    # Pausar para Cloudflare quando necessário
                    sucesso = baixar_pdf_processo(driver, numero, precisa_cloudflare)
                    
                    # Se chegou aqui, não precisa mais resolver Cloudflare
                    precisa_cloudflare = False
                    tentar_novamente = False
                    
                    if sucesso:
                        sucessos += 1
                    else:
                        falhas += 1
                    
                    # Aguardar tempo entre requisições
                    time.sleep(2)
                    
                except Exception as e:
                    erro_str = str(e)
                    
                    # Verificar se o driver morreu (várias formas possíveis)
                    erros_driver_morto = [
                        "HTTPConnectionPool",
                        "session",
                        "invalid session id",
                        "chrome not reachable",
                        "target window already closed",
                        "no such window",
                        "disconnected"
                    ]
                    
                    driver_morreu = any(palavra.lower() in erro_str.lower() for palavra in erros_driver_morto)
                    
                    if driver_morreu or isinstance(e, WebDriverException):
                        print(f"   ⚠️  Driver travou/morreu: {erro_str[:100]}")
                        print(f"   ⚠️  Recriando driver e tentando novamente...")
                        
                        # Fechar driver antigo (se possível)
                        try:
                            driver.quit()
                        except:
                            pass
                        
                        # Criar novo driver
                        time.sleep(3)
                        driver = criar_driver()
                        precisa_cloudflare = True  # Precisa resolver Cloudflare novamente
                        print(f"   ✓ Novo driver criado, continuando...")
                        # Tentar novamente com mesmo processo
                        tentar_novamente = True
                    else:
                        # Outro tipo de erro, não tentar novamente
                        falhas += 1
                        print(f"   ✗ Erro: {erro_str[:100]}")
                        tentar_novamente = False
    
    finally:
        try:
            driver.quit()
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
    executar_scraping()
