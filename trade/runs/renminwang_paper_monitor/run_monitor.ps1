Set-Location 'F:\ai\trade'
python 'runs\renminwang_paper_monitor\monitor.py' 2>&1 |
  Out-File -Append -Encoding utf8 'runs\renminwang_paper_monitor\scheduler.log'
