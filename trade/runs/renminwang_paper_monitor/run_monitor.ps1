$env:SERVER_CHAN_SENDKEY = [Environment]::GetEnvironmentVariable('SERVER_CHAN_SENDKEY', 'User')
Set-Location 'F:\ai\trade'
python 'runs\renminwang_paper_monitor\monitor.py' 2>&1 |
  Out-File -Append -Encoding utf8 'runs\renminwang_paper_monitor\scheduler.log'
