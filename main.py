import sys
import time
import requests
import io
import msvcrt
import random
from PIL import Image

from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from InquirerPy.utils import get_style

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich import box
from rich.align import Align
from rich.layout import Layout
from rich.live import Live

from api_service import MusicAPI
from player_service import PlayerService
from playlist_service import PlaylistManager

import os
if os.name == 'nt':
    os.system("color")

console = Console()
api = MusicAPI()
player = PlayerService()
playlist_manager = PlaylistManager()

custom_style = get_style(
    {
        "questionmark": "#e5c07b bold",
        "answer": "#61afef bold",
        "input": "#98c379",
        "pointer": "#e5c07b bold",
        "marker": "#e5c07b",
        "instruction": "#abb2bf",
    },
    style_override=False,
)

def get_ascii_thumbnail(url, width=32):
    if not url:
        return Align.left(Text("\n[Kapak Yok]", style="dim"))
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=5)
        img = Image.open(io.BytesIO(response.content)).convert("RGB")
        
        h_chars = int((img.height / img.width) * width * 0.5)
        if h_chars % 2 != 0:
            h_chars += 1
            
        if hasattr(Image, 'Resampling'):
            resample_method = Image.Resampling.LANCZOS
        else:
            resample_method = Image.LANCZOS
            
        img = img.resize((width, h_chars), resample_method)
        
        text = Text(no_wrap=True)
        for y in range(0, h_chars, 2):
            for x in range(width):
                r1, g1, b1 = img.getpixel((x, y))
                if y + 1 < h_chars:
                    r2, g2, b2 = img.getpixel((x, y + 1))
                else:
                    r2, g2, b2 = 0, 0, 0
                text.append("▀", style=f"#{r1:02x}{g1:02x}{b1:02x} on #{r2:02x}{g2:02x}{b2:02x}")
            text.append("\n")
        return text
    except Exception as e:
        return Text("[Resim Yuklenemedi]", style="red")

def format_time(ms):
    if ms < 0: ms = 0
    s = ms // 1000
    m = s // 60
    s = s % 60
    return f"{m}:{s:02d}"

def get_visualizer(width=80, is_playing=True):
    blocks = [' ', '▂', '▃', '▄', '▅', '▆']
    res = ""
    for _ in range(width):
        res += random.choice(blocks) if is_playing else ' '
    return Text(res, style="green")

def add_to_playlist_dialog(song):
    console.clear()
    pm = playlist_manager
    playlists = pm.get_all()
    
    choices = [Choice("NEW", "➕ Yeni Bir Çalma Listesi Oluştur")]
    for pl_name in playlists.keys():
        choices.append(Choice(pl_name, f"📁 {pl_name}"))
    choices.append(Choice("CANCEL", "❌ İptal"))
    
    sel = inquirer.select(
        message=f"'{song['title']}' hangi listeye eklensin?",
        choices=choices,
        style=custom_style
    ).execute()
    
    if sel == "CANCEL":
        return
        
    pl_name = sel
    if sel == "NEW":
        pl_name = inquirer.text(
            message="Yeni Çalma Listesinin Adı:",
            style=custom_style
        ).execute().strip()
        if not pl_name:
            console.print("[red]Geçersiz isim, iptal edildi.[/red]")
            time.sleep(1)
            return

    res = pm.add_song(pl_name, song)
    if res:
         console.print(f"\n[green]✓ Şarkı '{pl_name}' listesine eklendi![/green]")
    else:
         console.print(f"\n[yellow]Bu şarkı zaten '{pl_name}' listesinde var.[/yellow]")
    time.sleep(1.5)

def play_session(initial_song, playlist_context):
    song = initial_song
    queue = playlist_context
    idx = 0
    for i, s in enumerate(queue):
        if s['videoId'] == song['videoId']:
            idx = i
            break
            
    play_session.scroll_offset = max(0, idx - 4)
            
    resume = False
    paused = False

    while True:
        if not resume:
            player.play(song["url"])
            if not getattr(play_session, "vol_inited", False):
                player.set_volume(90)
                play_session.vol_inited = True
            time.sleep(1) # buffer time
            paused = False
        else:
            resume = False
            
        # Görseli bilerek "biraz daha küçük" çiziyoruz, pikseller çok dağılmasın diye.
        art_w = 40
            
        art_content = get_ascii_thumbnail(song.get("thumbnail"), width=art_w)
        next_up_items = queue[idx+1:idx+3]
        
        parts = song["duration"].split(":")
        fallback_length = 0
        if len(parts) == 2:
            fallback_length = int(parts[0]) * 60000 + int(parts[1]) * 1000
        elif len(parts) == 3:
            fallback_length = int(parts[0]) * 3600000 + int(parts[1]) * 60000 + int(parts[2]) * 1000

        def generate_player_panel(current_time, total_time, vol):
            layout = Layout()
            layout.split_column(
                Layout(name="header", size=3),
                Layout(name="main_top", size=20),
                Layout(name="progress", size=2),
                Layout(name="visualizer", size=3),
                Layout(name="bottom_info", size=7),
                Layout(name="footer", size=1)
            )
            
            # Header
            layout["header"].update(Text("< Back\nModernized CLI Player", style="bold green"))
            
            # Main Top (Art + Title)
            layout["main_top"].split_row(
                Layout(name="art_col", ratio=4),
                Layout(name="right_col", ratio=6)
            )
            layout["art_col"].split_column(
                Layout(name="art", size=16),
                Layout(name="title", size=4)
            )
            layout["art"].update(art_content)
            
            title_t = Text(f"{song['title']}\n", style="bold white")
            title_t.append(song['artist'], style="dim white")
            layout["title"].update(title_t)
            
            # Kaydırılabilir Liste (Playlist Queue)
            queue_text = Text()
            visible_items = 14 # Tahmini görünen liste satırı
            start_i = play_session.scroll_offset
            end_i = min(len(queue), start_i + visible_items)
            
            for i in range(start_i, end_i):
                q_song = queue[i]
                prefix = "▶ " if i == idx else "  "
                style = "bold green" if i == idx else "white"
                queue_text.append(f"{prefix}{i+1}. {q_song['title'][:40]}\n", style=style)
            
            if len(queue) > end_i:
                queue_text.append(f"  ... (+{len(queue) - end_i} tane daha) ...", style="dim")
                
            right_panel = Panel(queue_text, title="Listede Sırada", border_style="#2ecc71")
            layout["right_col"].update(right_panel)
            
            # Progress
            progress_ratio = 0
            if total_time and total_time > 0 and current_time >= 0:
                progress_ratio = current_time / total_time
            if progress_ratio > 1: progress_ratio = 1
            
            bar_len = console.width - 28
            if bar_len < 20: bar_len = 20
            
            filled = int(bar_len * progress_ratio)
            empty = bar_len - filled
            
            if filled > 0:
                bar = f"[#2ecc71]{'━'*(filled-1)}O[/][dim]{'━'*empty}[/]  [dim]{format_time(current_time)} / {format_time(total_time)}[/]"
            else:
                bar = f"[#2ecc71]O[/][dim]{'━'*empty}[/]  [dim]{format_time(current_time)} / {format_time(total_time)}[/]"
                
            layout["progress"].update(Text.from_markup(bar))
            
            # Visualizer
            layout["visualizer"].update(get_visualizer(bar_len, is_playing=not paused))
            
            # Bottom Info
            if vol < 0: vol = 0
            if vol > 100: vol = 100
            v_bars = int(vol / 10)
            v_text = f"VOL: [#2ecc71][{'|'*v_bars}{' '*(10-v_bars)}] {vol}%[/]"
            
            nu_text = Text.from_markup(f"{v_text}\n\n[dim]Next Up[/dim]\n")
            for i, n in enumerate(next_up_items):
                nu_text.append(f"{idx+2+i}. {n['title']} - {n['artist']}\n", style="white")
            layout["bottom_info"].update(nu_text)
            
            # Footer
            layout["footer"].update(Text("[Q] ÇIKIŞ  [SPACE] DURDUR/OYNAT  [P] LİSTEYE EKLE  [N] SONRAKİ  [YUKARI/AŞAĞI] KAYDIR  [+ / -] SES", style="dim"))
            
            return Panel(
                layout,
                border_style="#2d3436",
                box=box.ROUNDED,
                padding=(1, 2)
            )

        exit_reason = None
        with Live(generate_player_panel(0, fallback_length, getattr(play_session, "last_vol", 90)), refresh_per_second=10, screen=True) as live:
            while True:
                current_time = player.get_time()
                total_time = player.get_length()
                if total_time <= 0:
                    total_time = fallback_length
                    
                vol = player.get_volume()
                play_session.last_vol = vol
                
                live.update(generate_player_panel(current_time, total_time, vol))
                
                if msvcrt.kbhit():
                    key = msvcrt.getch()
                    if key in (b'b', b'q', b'B', b'Q'):
                        exit_reason = "back"
                        break
                    elif key in (b'n', b'N'):
                        if idx + 1 < len(queue):
                            exit_reason = "next"
                        break
                    elif key in (b'p', b'P'):
                        exit_reason = "playlist"
                        break
                    elif key == b' ':
                        paused = not paused
                        player.pause()
                    elif key in (b'+', b'=', b'k', b'K'):
                        player.set_volume(min(100, vol + 5))
                    elif key in (b'-', b'_', b'j', b'J'):
                        player.set_volume(max(0, vol - 5))
                    elif key == b'\xe0':
                        arr = msvcrt.getch()
                        if arr == b'H': # Up
                            play_session.scroll_offset = max(0, play_session.scroll_offset - 1)
                        elif arr == b'P': # Down
                            play_session.scroll_offset = min(max(0, len(queue) - 4), play_session.scroll_offset + 1)

                # Auto progress
                if total_time > 0 and current_time >= total_time - 1500 and not player.is_playing() and not paused:
                    time.sleep(0.5)
                    if current_time >= total_time - 1500 and not player.is_playing():
                        if idx + 1 < len(queue):
                            exit_reason = "next"
                        else:
                            exit_reason = "back"
                        break

        if exit_reason == "back":
            player.stop()
            break
            
        elif exit_reason == "next":
            idx += 1
            song = queue[idx]
            play_session.scroll_offset = max(0, idx - 4)
            
        elif exit_reason == "playlist":
            add_to_playlist_dialog(song)
            resume = True

def search_menu():
    console.clear()
    console.print(Panel("[bold #2ecc71]Modernized CLI Player[/] - Arama", border_style="#2d3436"))
    
    query = inquirer.text(
        message="Şarkı veya sanatçı arayın (Çıkmak için boş bırakın):",
        style=custom_style
    ).execute()
    
    if not query.strip():
        return False
        
    with console.status(f"[bold yellow]Arama yapılıyor '{query}'...[/bold yellow]"):
        results = api.search(query)
        
    if not results:
        console.print("[red]Sonuç bulunamadı.[/red]")
        time.sleep(2)
        return True
        
    choices = [Choice("BACK", "<- Geri Dön")]
    for item in results:
        choices.append(Choice(item, f"{item['title']} - {item['artist']}"))
        
    sel = inquirer.select(
        message="Seçtiğiniz şarkıyı dinleyin:",
        choices=choices,
        style=custom_style,
        pointer="> "
    ).execute()
    
    if sel != "BACK":
        play_session(sel, results)
        
    return True

def playlists_menu():
    while True:
        console.clear()
        pm = playlist_manager
        playlists = pm.get_all()
        
        if not playlists:
            console.print("[yellow]Henüz hiç çalma listeniz yok. Müzik çalarken klavyede [P] tuşuna basarak listeye şarkı ekleyebilirsiniz.[/yellow]")
            time.sleep(4)
            return
            
        choices = [Choice("BACK", "<- Ana Menüye Dön")]
        for pl_name, songs in playlists.items():
            choices.append(Choice(pl_name, f"📁 {pl_name} ({len(songs)} Şarkı)"))
            
        pl_name = inquirer.select(
            message="Görüntülemek istediğiniz listeyi seçin:",
            choices=choices,
            style=custom_style,
            pointer="> "
        ).execute()
        
        if pl_name == "BACK":
            return
            
        playlist_actions(pl_name, playlists[pl_name])

def playlist_actions(pl_name, songs):
    if not songs:
        console.print(f"[red]{pl_name} listesi boş.[/red]")
        time.sleep(2)
        return
        
    choices = [
        Choice("PLAY", "▶ Listeyi Çal (Sırayla)"),
        Choice("RECOMMEND", "💡 Bu Listeye Göre Akıllı Öneriler Bul (Radyo Karışımı)"),
        Choice("BACK", "<- Playlistlere Dön")
    ]
    
    act = inquirer.select(
        message=f"{pl_name} listesi için işlem seçin:",
        choices=choices,
        style=custom_style,
        pointer="> "
    ).execute()
    
    if act == "PLAY":
        play_session(songs[0], songs)
    elif act == "RECOMMEND":
        seed = random.choice(songs)
        with console.status(f"[bold yellow]Akıllı öneriler hesaplanıyor... (Referans Şarkı: {seed['title']})[/bold yellow]"):
            recs = api.get_recommendations(seed["videoId"])
            
        if not recs:
            console.print("[red]Öneri bulunamadı![/red]")
            time.sleep(2)
            return
            
        rec_choices = [Choice("BACK", "<- Geri Dön")]
        for item in recs:
            rec_choices.append(Choice(item, f"✨ {item['title']} - {item['artist']}"))
            
        sel = inquirer.select(
            message="Akıllı Öneriler: Hangi şarkıdan başlamak istersiniz?",
            choices=rec_choices,
            style=custom_style,
            pointer="> "
        ).execute()
        
        if sel != "BACK":
             play_session(sel, recs)

def main_menu():
    console.clear()
    console.print(Panel("[bold #2ecc71]Modernized CLI Player[/] - Ana Menü", border_style="#2d3436"))
    
    choices = [
        Choice("SEARCH", "🎵 Şarkı veya Sanatçı Ara"),
        Choice("PLAYLISTS", "📂 Çalma Listelerim (Playlists)"),
        Choice("QUIT", "❌ Çıkış")
    ]
    
    sel = inquirer.select(
        message="Ne yapmak istersiniz?",
        choices=choices,
        style=custom_style,
        pointer="> "
    ).execute()
    
    if sel == "SEARCH":
        search_menu()
    elif sel == "PLAYLISTS":
        playlists_menu()
    elif sel == "QUIT":
        return False
    return True

def main():
    while True:
        try:
            if not main_menu():
                console.print("\n[dim]Görüşmek Üzere...[/dim]")
                break
        except KeyboardInterrupt:
            console.print("\n[dim]Uygulama Kapatılıyor...[/dim]")
            player.stop()
            sys.exit(0)
        except Exception as e:
            console.print(f"Hata: {e}")
            time.sleep(2)

if __name__ == "__main__":
    main()
