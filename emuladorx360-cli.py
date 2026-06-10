import evdev
import json
import time
from evdev.ecodes import *
from evdev import UInput

#_________________________________________________________________________________
#           SEÇÃO DE CONFIGURAÇÕES - CUSTOMIZE SEU DISPOSITIVO AQUI
#_________________________________________________________________________________

#DESCUBRA O NOME DO SEU CONTROLE OU DISPOSITIVO COM O COMANDO NO TERMINAL: sudo evtest

#(substitua o numero abaixo pelo event respectivo)
caminho_fisico = '/dev/input/event16'

#--não altere essa linha:
controle_fisico = evdev.InputDevice(caminho_fisico)



# ABAIXO ESTÁ O EFEITO DE GRAB ONDE ELE SEGURA O DISPOSITIVO EM QUESTÃO PARA PREVENIR CLIQUES DUPLOS, 
# DESATIVE COM SABEDORIA POIS PODE OCASIONAR TRAPAÇA EM ANTI-CHEAT DE JOGOS. (desative comentando a linha, usando # na frente)
# ATENÇÃO: SE USAR TECLADO OU MOUSE, E DESATIVAR O GRAB, VAI FICAR SEM COMANDOS ATÉ REINICIAR O COMPUTADOR!!!

controle_fisico.grab()



######################### CONFIGURAÇÃO DO EMULADOR ################################
# 
#  AQUI ONDE VOCE VAI DIZER O NOME DA TECLA QUE SEU CONTROLE FORNECE E SERÁ EMULADA UMA TECLA DE XBOX.

# NOME DOS BOTÕES, DESCUBRA COM o comando: sudo evtest
#botão "tal" é igual a qual no seu controle?


# NÃO ALTERE A PRIMEIRA PARTE E APÓS = DIGA O BOTÃO DO SEU CONTROLE.

#EXEMPLO:
#BUTTON_A = sua tecla


BUTTON_A = BTN_SOUTH
BUTTON_X = BTN_NORTH
BUTTON_B = BTN_EAST
BUTTON_Y = BTN_WEST

BUTTON_SELECT = BTN_SELECT
BUTTON_START = BTN_START


BUTTON_L1 = BTN_TL
BUTTON_R1 = BTN_TR


#EIXO X (ESQUERDA DIREITA) DOS BOTÕES DIRECIONAL (D-PAD):
DIRECIONAL_X = ABS_HAT0X

#EIXO Y (CIMA BAIXO) DOS BOTÕES DIRECIONAL (D-PAD):
DIRECIONAL_Y = ABS_HAT0Y


# EIXO X (ESQUERDA DIREITA) DO ANALÓGICO ESQUERDO:
ANALOGICOE_X = ABS_X

#EIXO Y (CIMA BAIXO) DO ANALÓGICO ESQUERDO:
ANALOGICOE_Y = ABS_Y


#EIXO X (ESQUERDA DIREITA) DO ANALÓGICO DIREITO:
ANALOGICOD_X = ABS_RZ

#EIXO Y (CIMA BAIXO) DO ANALÓGICO DIREITO:
ANALOGICOD_Y = ABS_Z


GATILHO_L2 = ABS_BRAKE

GATILHO_R2 = ABS_GAS

BUTTON_L3 = BTN_THUMBL
BUTTON_R3 = BTN_THUMBR


#_________________________________________________________________________________
#           ⚙️ CONFIGURAÇÃO DE SENSIBILIDADE DOS GATILHOS ⚙️
#_________________________________________________________________________________

# Ajuste o valor abaixo (0-100) para quando o gatilho deve atingir 100%
# Padrão: 90 significa que ao apertar 90% do gatilho físico, já emula 100%
# Valores menores = gatilho mais sensível (ex: 80, 70)
# Valores maiores = gatilho menos sensível (ex: 95, 100)

SENSIBILIDADE_R2 = 85  # Gatilho R2 (GAS)
SENSIBILIDADE_L2 = 85  # Gatilho L2 (BRAKE)

# END




#_________________________________________________________________________________
#                 ⚠️ NÃO ALTERE O CÓDIGO ABAIXO / DON'T CHANGE BELOW  ⚠️
#_________________________________________________________________________________


def ajustar_gatilho(valor, valor_max, sensibilidade):
    """
    Ajusta a curva do gatilho para atingir 100% mais facilmente
    
    valor: valor atual do gatilho (0-valor_max)
    valor_max: valor máximo do gatilho físico
    sensibilidade: percentual onde deve atingir 100% (0-100)
    """
    if sensibilidade >= 100:
        return valor  # Sem ajuste
    
    # Calcula o ponto de corte baseado na sensibilidade
    ponto_corte = int((sensibilidade / 100.0) * valor_max)
    
    # Se já passou do ponto de corte, retorna o máximo
    if valor >= ponto_corte:
        return valor_max
    
    # Escala linearmente de 0 até o ponto de corte
    return int((valor / ponto_corte) * valor_max)


capabilites = {
    EV_KEY: [
        BTN_SOUTH,
        BTN_EAST,
        BTN_NORTH,
        BTN_WEST,
        BTN_TL,
        BTN_TR,
        BTN_SELECT,
        BTN_START,
        BTN_MODE,
        BTN_THUMBL,
        BTN_THUMBR,
    ],
    EV_ABS: [
        (ABS_X, evdev.AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)),
        (ABS_Y, evdev.AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)),
        (ABS_Z, evdev.AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)),
        (ABS_RX, evdev.AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)),
        (ABS_RY, evdev.AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)),
        (ABS_RZ, evdev.AbsInfo(value=0, min=0, max=255, fuzz=0, flat=0, resolution=0)),
        (ABS_HAT0X, evdev.AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0)),
        (ABS_HAT0Y, evdev.AbsInfo(value=0, min=-1, max=1, fuzz=0, flat=0, resolution=0)),
    ]
}

virtual_xbox = UInput(capabilites, name="EDIRLEI TECHNOLOGIES - SUPER1", vendor=0x045e, product=0x028e)

mapa_botoes = {
    BUTTON_A: BTN_SOUTH,
    BUTTON_B: BTN_EAST,
    BUTTON_X: BTN_NORTH,
    BUTTON_Y: BTN_WEST,
    BUTTON_SELECT: BTN_SELECT,
    BUTTON_START: BTN_START,
    BUTTON_L1: BTN_TL,
    BUTTON_R1: BTN_TR,
    BUTTON_L3: BTN_THUMBL,
    BUTTON_R3: BTN_THUMBR,
}

print("Mapeador iniciado! Pressione Ctrl+C para sair.")
print(f"⚙️  Sensibilidade R2: {SENSIBILIDADE_R2}% | L2: {SENSIBILIDADE_L2}%")

def processar_eventos():
    """Processa os eventos do controle"""
    try:
        for event in controle_fisico.read_loop():
            
            if event.type == EV_KEY:
                if event.code in mapa_botoes:
                    novo_code = mapa_botoes[event.code]
                    virtual_xbox.write(EV_KEY, novo_code, event.value)
                    virtual_xbox.syn()

            elif event.type == EV_ABS:

                if event.code == ANALOGICOE_X:
                    virtual_xbox.write(EV_ABS, ABS_X, event.value)
                    virtual_xbox.syn()

                elif event.code == ANALOGICOE_Y:
                    virtual_xbox.write(EV_ABS, ABS_Y, event.value)
                    virtual_xbox.syn()

                elif event.code == ANALOGICOD_X:
                    virtual_xbox.write(EV_ABS, ABS_RY, event.value)
                    virtual_xbox.syn()

                elif event.code == ANALOGICOD_Y:
                    virtual_xbox.write(EV_ABS, ABS_RX, event.value)
                    virtual_xbox.syn()

                elif event.code == DIRECIONAL_X:
                    virtual_xbox.write(EV_ABS, ABS_HAT0X, event.value)
                    virtual_xbox.syn()

                elif event.code == DIRECIONAL_Y:
                    virtual_xbox.write(EV_ABS, ABS_HAT0Y, event.value)
                    virtual_xbox.syn()

                elif event.code == GATILHO_L2:
                    # Aplica o ajuste de sensibilidade no L2
                    valor_ajustado = ajustar_gatilho(event.value, 255, SENSIBILIDADE_L2)
                    virtual_xbox.write(EV_ABS, ABS_Z, valor_ajustado)
                    virtual_xbox.syn()

                elif event.code == GATILHO_R2:
                    # Aplica o ajuste de sensibilidade no R2
                    valor_ajustado = ajustar_gatilho(event.value, 255, SENSIBILIDADE_R2)
                    virtual_xbox.write(EV_ABS, ABS_RZ, valor_ajustado)
                    virtual_xbox.syn()

    except (OSError, IOError):
        # Controle desconectado
        return False
    
    return True

def aguardar_reconexao():
    """Aguarda o controle se reconectar"""
    print("⚠️  Controle desconectado! Aguardando reconexão...")
    while True:
        try:
            time.sleep(1)
            # Tenta reabrir o dispositivo
            global controle_fisico
            controle_fisico = evdev.InputDevice(caminho_fisico)
            controle_fisico.grab()
            print("✓ Controle reconectado! Continuando...")
            return True
        except:
            pass

try:
    while True:
        if not processar_eventos():
            aguardar_reconexao()
            
except KeyboardInterrupt:
    print("\nEncerrando...")
    controle_fisico.ungrab()
    virtual_xbox.close()
