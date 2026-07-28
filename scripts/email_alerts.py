#!/usr/bin/env python3
"""
📧 NEXYROTH Email Alert Handler
Sends HTML email digests for GO signals, TP hits, and SL hits
"""
import requests
import json
from datetime import datetime
import os

RESEND_API_KEY = os.getenv('RESEND_API_KEY', '')
ALERT_EMAIL = os.getenv('ALERT_EMAIL_TO', '')

def send_email(subject, html_body, email_to=None):
    """Send email via Resend API"""
    if not email_to:
        email_to = ALERT_EMAIL
    
    try:
        resp = requests.post(
            'https://api.resend.com/emails',
            headers={
                'Authorization': f'Bearer {RESEND_API_KEY}',
                'Content-Type': 'application/json'
            },
            json={
                'from': 'onboarding@resend.dev',
                'to': email_to,
                'subject': subject,
                'html': html_body
            },
            timeout=10
        )
        
        if resp.status_code == 200:
            data = resp.json()
            print(f"✅ Email sent: {data.get('id')}")
            return True
        else:
            print(f"❌ Email failed: {resp.status_code}")
            return False
    except Exception as e:
        print(f"❌ Error sending email: {e}")
        return False

def format_go_signal(symbol, price, entry, sl, tp1, tp2, ratio, gain_24h, fr):
    """Format GO signal email"""
    html = f'''
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; background: #0a0e27; color: #fff; padding: 20px; border-radius: 8px;">
        <h2 style="color: #00d4ff; margin-top: 0;">🟢 GO SIGNAL - ENTRY OPPORTUNITY</h2>
        
        <div style="background: #1a1f3a; padding: 15px; border-radius: 6px; margin: 15px 0; border-left: 4px solid #00d4ff;">
            <h3 style="margin-top: 0; color: #00d4ff;">{symbol}</h3>
            <p style="margin: 5px 0;"><strong>Current Price:</strong> ${price:.6f}</p>
            <p style="margin: 5px 0;"><strong>24h Gain:</strong> <span style="color: #00ff00;">+{gain_24h:.2f}%</span></p>
            <p style="margin: 5px 0;"><strong>Funding Rate:</strong> <span style="color: #00ff00;">{fr:.2f}%</span></p>
            <p style="margin: 5px 0;"><strong>Whale Ratio:</strong> {ratio:.2f}</p>
        </div>
        
        <div style="background: #1a1f3a; padding: 15px; border-radius: 6px; margin: 15px 0;">
            <h4 style="color: #00d4ff; margin-top: 0;">Position Setup:</h4>
            <table style="width: 100%; border-collapse: collapse;">
                <tr style="border-bottom: 1px solid #333;">
                    <td style="padding: 8px; color: #888;">Entry</td>
                    <td style="padding: 8px; text-align: right; color: #fff;">${entry:.6f}</td>
                </tr>
                <tr style="border-bottom: 1px solid #333;">
                    <td style="padding: 8px; color: #888;">Stop Loss</td>
                    <td style="padding: 8px; text-align: right; color: #ff4444;">${sl:.6f} (-7.5%)</td>
                </tr>
                <tr style="border-bottom: 1px solid #333;">
                    <td style="padding: 8px; color: #888;">Take Profit 1</td>
                    <td style="padding: 8px; text-align: right; color: #00ff00;">${tp1:.6f} (+5.9%)</td>
                </tr>
                <tr>
                    <td style="padding: 8px; color: #888;">Take Profit 2</td>
                    <td style="padding: 8px; text-align: right; color: #00ff00;">${tp2:.6f} (+13.5%)</td>
                </tr>
            </table>
        </div>
        
        <div style="background: #1a1f3a; padding: 15px; border-radius: 6px; margin: 15px 0; border-left: 4px solid #00ff00;">
            <p style="margin: 0; color: #00ff00;"><strong>✅ Strategy:</strong> TLMUSDT Winning Pattern</p>
            <p style="margin: 5px 0; color: #888; font-size: 12px;">High momentum + strong whale support + negative funding</p>
        </div>
        
        <p style="color: #888; font-size: 12px; margin-top: 20px;">
            <strong>Next scan:</strong> {datetime.utcnow().strftime('%H:%M UTC')} + 15 minutes<br>
            <strong>Dashboard:</strong> https://tradesnpr-fsjswsms.manus.space
        </p>
    </div>
    '''
    return html

def send_go_signal(symbol, price, entry, sl, tp1, tp2, ratio, gain_24h, fr):
    """Send GO signal email"""
    html = format_go_signal(symbol, price, entry, sl, tp1, tp2, ratio, gain_24h, fr)
    subject = f"🟢 GO SIGNAL: {symbol} @ ${price:.6f}"
    return send_email(subject, html)

def send_daily_summary(candidates):
    """Send daily summary of top candidates"""
    rows = ""
    for i, cand in enumerate(candidates[:5], 1):
        rows += f'''
        <tr style="border-bottom: 1px solid #333;">
            <td style="padding: 10px;">{i}. {cand['symbol']}</td>
            <td style="padding: 10px; text-align: right;">${cand['price']:.6f}</td>
            <td style="padding: 10px; text-align: right; color: #00ff00;">+{cand['gain_24h']:.2f}%</td>
            <td style="padding: 10px; text-align: right;">{cand['score']:.0f}</td>
            <td style="padding: 10px; text-align: right;">{cand['score']:.0f}</td>
        </tr>
        '''
    
    html = f'''
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; background: #0a0e27; color: #fff; padding: 20px; border-radius: 8px;">
        <h2 style="color: #00d4ff; margin-top: 0;">📊 Daily Summary - Top 5 Candidates</h2>
        <p style="color: #888;">Scan Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
        
        <table style="width: 100%; border-collapse: collapse; background: #1a1f3a; border-radius: 6px; overflow: hidden;">
            <thead>
                <tr style="background: #00d4ff; color: #000;">
                    <th style="padding: 10px; text-align: left;">Symbol</th>
                    <th style="padding: 10px; text-align: right;">Price</th>
                    <th style="padding: 10px; text-align: right;">24h%</th>
                    <th style="padding: 10px; text-align: right;">Ratio</th>
                    <th style="padding: 10px; text-align: right;">Score</th>
                </tr>
            </thead>
            <tbody>
                {rows}
            </tbody>
        </table>
        
        <p style="color: #888; font-size: 12px; margin-top: 20px;">
            Strategy: TLMUSDT Winning Pattern<br>
            Next scan: {datetime.utcnow().strftime('%H:%M UTC')} + 15 minutes
        </p>
    </div>
    '''
    
    subject = f"📊 NEXYROTH Daily Summary - {datetime.utcnow().strftime('%Y-%m-%d')}"
    return send_email(subject, html)

if __name__ == '__main__':
    # Test email
    print("Testing email alert system...")
    html = format_go_signal(
        'VANRYUSDT', 0.009248, 0.009248, 0.00850, 0.00980, 0.01050,
        1.75, 57.96, -4.61
    )
    send_email("🟢 TEST: NEXYROTH Email Alerts Active", html)

