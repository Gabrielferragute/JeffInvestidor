"""
Script de testes para validar o funcionamento das ferramentas financeiras do Jeff.
Execute diretamente com:
    python test_tools.py
"""

import sys

# Garantir suporte a UTF-8 no terminal Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from bot_jeff import (
    get_taxa_selic,
    get_bitcoin_price,
    get_asset_price,
    code_interpreter
)

def run_tests():
    print("=" * 60)
    print("[TEST] Iniciando testes das ferramentas financeiras do Jeff...")
    print("=" * 60)

    # 1. Teste da Taxa Selic (Banco Central do Brasil)
    print("\n1. Testando get_taxa_selic():")
    selic_res = get_taxa_selic()
    print(f"   -> Retorno: {selic_res}")
    assert "Selic Meta:" in selic_res or "Error" not in selic_res, "Falha ao obter Selic"

    # 2. Teste do Preço do Bitcoin (CoinGecko)
    print("\n2. Testando get_bitcoin_price():")
    btc_res = get_bitcoin_price()
    print(f"   -> Retorno: {btc_res}")
    assert "Bitcoin Price" in btc_res, "Falha ao obter preco do BTC"

    # 3. Teste de Ações/FIIs da B3 (Yahoo Finance)
    print("\n3. Testando get_asset_price('PETR4'):")
    petr_res = get_asset_price("PETR4")
    print(f"   -> Retorno: {petr_res}")
    assert "Price of PETR4.SA" in petr_res, "Falha ao obter cotacao PETR4"

    print("\n4. Testando get_asset_price('MXRF11'):")
    mxrf_res = get_asset_price("MXRF11")
    print(f"   -> Retorno: {mxrf_res}")
    assert "Price of MXRF11.SA" in mxrf_res, "Falha ao obter cotacao MXRF11"

    # 4. Teste do Interpretador de Código Python
    print("\n5. Testando code_interpreter (Calculo de Juros Compostos):")
    calc_code = """
aporte_mensal = 500
taxa_mensal = 0.008 # aprox 10% a.a.
meses = 12 * 5 # 5 anos
montante = 0
for _ in range(meses):
    montante = (montante + aporte_mensal) * (1 + taxa_mensal)
print(f"Montante acumulado em 5 anos: R$ {montante:,.2f}")
"""
    calc_res = code_interpreter(calc_code)
    print(f"   -> Retorno:\n   {calc_res.strip()}")
    assert "Montante acumulado" in calc_res, "Falha na execucao do code_interpreter"

    print("\n" + "=" * 60)
    print("[SUCCESS] Todos os testes das ferramentas passaram com sucesso!")
    print("=" * 60)

if __name__ == "__main__":
    run_tests()
