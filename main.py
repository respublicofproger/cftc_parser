import dash
from dash import dcc, html, Input, Output
import plotly.graph_objects as go
import pandas as pd
import numpy as np
import update_data
import requests
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Обновляем данные:
update_data.update_history_file()
# Загрузка данных
df = pd.read_excel("history.xlsx", sheet_name="XLS")
df['As_of_Date_In_Form_YYMMDD'] = pd.to_datetime(df['As_of_Date_In_Form_YYMMDD'], format='%y%m%d')
df = df.sort_values(by='As_of_Date_In_Form_YYMMDD')

# Расчет базовых переменных
df['Asset_Manager_Net'] = df['Asset_Mgr_Positions_Long_All'] - df['Asset_Mgr_Positions_Short_All']
df['Leveraged_Funds_Net'] = df['Lev_Money_Positions_Long_All'] - df['Lev_Money_Positions_Short_All']
df['Dealer_Net'] = df['Dealer_Positions_Long_All'] - df['Dealer_Positions_Short_All']
df['Other_Net'] = df['Other_Rept_Positions_Long_All'] - df['Other_Rept_Positions_Short_All']
df['Nonreportable'] = df['NonRept_Positions_Long_All'] - df['NonRept_Positions_Short_All']

# Опции участников
participant_options = {
    'Asset_Manager_Net': 'Asset Managers',
    'Leveraged_Funds_Net': 'Leveraged Funds',
    'Dealer_Net': 'Dealers',
    'Other_Net': 'Other Reportables',
    'Nonreportable': 'Nonreportable',
}

# Методы дивергенции
indicator_options = {
    'abs_diff': 'Абсолютная разница',
    'rel_diff': 'Относительная разница',
    'percent_delta': 'Процентная дельта',
    'crossover': 'Кроссовер (1 / -1)',
    'divergence_index': 'Нормализованная абсолютная разница',
    'percentage_difference': "Процентная разница между участниками"
}

def setup_session():
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retries))
    return session
    
# Функция для получения данных BTC/USDT с Binance
def get_btc_data():
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        session = setup_session()
        url = 'https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=500'
        response = session.get(url, timeout=15)
        response.raise_for_status()  # Проверка на ошибки HTTP
        data = response.json()
        
        df_btc = pd.DataFrame(data, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 
                                           'close_time', 'quote_asset_volume', 'trades', 
                                           'taker_buy_base', 'taker_buy_quote', 'ignore'])
        df_btc['timestamp'] = pd.to_datetime(df_btc['timestamp'], unit='ms')
        df_btc['close'] = df_btc['close'].astype(float)
        return df_btc
    except Exception as e:
        print(f"Error fetching BTC data: {e}")
        # Возвращаем пустой DataFrame с той же структурой
        return pd.DataFrame(columns=['timestamp', 'close'])

# Получаем данные BTC
df_btc = get_btc_data()

# Dash app
app = dash.Dash(__name__)
server = app.server
graph_config = {'scrollZoom': True}

app.layout = html.Div([
    html.Div([
        html.H3("Выбор участников (ровно 2)"),
        dcc.Checklist(
            id='participant-checklist',
            options=[{'label': name, 'value': key} for key, name in participant_options.items()],
            value=['Asset_Manager_Net', 'Leveraged_Funds_Net'],
            inputStyle={'margin-right': '10px', 'margin-left': '20px'}
        ),
        html.H3("Индикаторы дивергенции"),
        dcc.Checklist(
            id='indicator-checklist',
            options=[{'label': name, 'value': key} for key, name in indicator_options.items()],
            value=['abs_diff'],
            inputStyle={'margin-right': '10px', 'margin-left': '20px'}
        ),
    ], style={'width': '20%', 'display': 'inline-block', 'verticalAlign': 'top', 'padding': '20px'}),

    html.Div([
        dcc.Graph(id='main-graph', config=graph_config),
        dcc.Graph(
            id='btc-graph',
            figure={
                'data': [
                    go.Scatter(
                        x=df_btc['timestamp'],
                        y=df_btc['close'],
                        name='BTC/USDT Price'
                    )
                ],
                'layout': go.Layout(
                    title='BTC/USDT Price (Binance)',
                    xaxis={'title': 'Date'},
                    yaxis={'title': 'Price (USDT)'},
                    template="plotly_dark"
                )
            },
            config=graph_config
        )
    ], style={'width': '75%', 'display': 'inline-block'})
])

@app.callback(
    Output('main-graph', 'figure'),
    Input('participant-checklist', 'value'),
    Input('indicator-checklist', 'value')
)
def update_graph(selected_participants, selected_indicators):
    fig = go.Figure()

    # Проверим, выбрано ли 2 участника
    if len(selected_participants) != 2:
        fig.update_layout(
            title="Выберите ровно 2 участника для расчета дивергенции",
            template="plotly_dark"
        )
        return fig

    p1, p2 = selected_participants
    p1_series = df[p1]
    p2_series = df[p2]

    # Добавляем базовые графики участников
    fig.add_trace(go.Scatter(
        x=df['As_of_Date_In_Form_YYMMDD'],
        y=p1_series,
        name=participant_options[p1]
    ))
    fig.add_trace(go.Scatter(
        x=df['As_of_Date_In_Form_YYMMDD'],
        y=p2_series,
        name=participant_options[p2]
    ))

    # Расчет и добавление выбранных индикаторов
    for ind in selected_indicators:
        if ind == 'abs_diff':
            y = abs(p1_series - p2_series)
        elif ind == 'rel_diff':
            y = abs(p1_series - p2_series) / (abs(p1_series) + abs(p2_series)).replace(0, np.nan)
        elif ind == 'percent_delta':
            y = abs((p1_series - p2_series) / p1_series.shift(1)) * 100
        elif ind == 'crossover':
            y = np.where(p1_series > p2_series, 1, -1)
        elif ind == 'divergence_index':
            absolute_diff = abs(p1_series - p2_series)
            max_diff = absolute_diff.max()
            y = (absolute_diff / max_diff) * 100
        elif ind == 'percentage_difference':
            net_p1 = p1_series  # предполагая, что p1_series уже net позиция
            net_p2 = p2_series  # предполагая, что p2_series уже net позиция
            avg_pos = (net_p1 + net_p2) / 2
            y = (abs(net_p1 - net_p2) / avg_pos.replace(0, np.nan)) * 100
        else:
            continue

        fig.add_trace(go.Scatter(
            x=df['As_of_Date_In_Form_YYMMDD'],
            y=y,
            name=indicator_options[ind],
            mode='lines',
            line=dict(dash='dot')
        ))

    fig.update_layout(
        title_text="Net Positions & Divergence Analysis",
        xaxis_title="Date",
        height=600,
        template="plotly_dark",
        dragmode="pan",
        hovermode="x unified",
        margin=dict(l=50, r=50, t=50, b=50),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        )
    )
    return fig

if __name__ == '__main__':
    app.run(debug=True)
