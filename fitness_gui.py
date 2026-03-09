# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import os
import threading
import sys
from pathlib import Path
from fitness_calculate import run_fitness_calculation

class FitnessGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("测量数据代表值计算工具 v1.0")
        self.root.geometry("700x500")
        
        # 设置样式
        style = ttk.Style()
        style.configure("TButton", padding=5)
        style.configure("TLabel", padding=5)
        
        self.create_widgets()
        
    def create_widgets(self):
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 文件选择部分
        file_frame = ttk.LabelFrame(main_frame, text="文件选择", padding="10")
        file_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(file_frame, text="输入表格文件：").grid(row=0, column=0, sticky=tk.W)
        self.file_path_var = tk.StringVar()
        self.file_entry = ttk.Entry(file_frame, textvariable=self.file_path_var, width=60)
        self.file_entry.grid(row=0, column=1, padx=5)
        
        ttk.Button(file_frame, text="浏览…", command=self.browse_file).grid(row=0, column=2)
        
        # 操作部分
        btn_frame = ttk.Frame(main_frame, padding="5")
        btn_frame.pack(fill=tk.X, pady=5)
        
        self.run_btn = ttk.Button(btn_frame, text="开始计算", command=self.start_calculation)
        self.run_btn.pack(side=tk.LEFT, padx=5)
        
        self.open_dir_btn = ttk.Button(btn_frame, text="打开输出目录", command=self.open_output_dir, state=tk.DISABLED)
        self.open_dir_btn.pack(side=tk.LEFT, padx=5)
        
        # 日志输出部分
        log_frame = ttk.LabelFrame(main_frame, text="运行日志", padding="10")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.log_area = scrolledtext.ScrolledText(log_frame, height=15, wrap=tk.WORD)
        self.log_area.pack(fill=tk.BOTH, expand=True)
        
        # 进度条
        self.progress = ttk.Progressbar(main_frame, orient=tk.HORIZONTAL, length=100, mode='indeterminate')
        self.progress.pack(fill=tk.X, pady=5)
        
    def browse_file(self):
        filename = filedialog.askopenfilename(
            title="选择输入文件",
            filetypes=[("表格文件", "*.xlsx *.xls")]
        )
        if filename:
            self.file_path_var.set(filename)
            self.log(f"已选择文件：{filename}")
            
    def log(self, message):
        self.log_area.insert(tk.END, f"{message}\n")
        self.log_area.see(tk.END)
        
    def open_output_dir(self):
        if hasattr(self, 'last_output_dir'):
            os.startfile(self.last_output_dir)
            
    def start_calculation(self):
        input_file = self.file_path_var.get()
        if not input_file or not os.path.exists(input_file):
            messagebox.showerror("错误", "请先选择有效的输入文件！")
            return
            
        # 生成输出文件名
        in_path = Path(input_file)
        out_name = f"代表值_S1均值+S2均值_{in_path.stem}.xlsx"
        output_file = in_path.parent / out_name
        
        self.last_output_dir = str(in_path.parent)
        
        # 禁用按钮，启动进度条
        self.run_btn.config(state=tk.DISABLED)
        self.progress.start()
        self.log("—" * 40)
        self.log(f"开始处理：{in_path.name}")
        self.log(f"输出文件：{out_name}")
        
        # 在线程中运行
        thread = threading.Thread(target=self.run_process, args=(input_file, output_file))
        thread.daemon = True
        thread.start()
        
    def run_process(self, input_file, output_file):
        try:
            summary = run_fitness_calculation(input_file, output_file)
            
            # 回到主线程更新 UI
            self.root.after(0, self.on_success, summary)
        except Exception as e:
            # 回到主线程更新 UI
            self.root.after(0, self.on_error, str(e))
            
    def on_success(self, summary):
        self.progress.stop()
        self.run_btn.config(state=tk.NORMAL)
        self.open_dir_btn.config(state=tk.NORMAL)
        
        self.log("计算成功完成！")
        for k, v in summary.items():
            self.log(f"－ {k}：{v}")
        self.log("—" * 40)
        
        messagebox.showinfo("成功", f"计算完成！\n结果已保存至: {os.path.basename(self.last_output_dir)}")
        
    def on_error(self, error_msg):
        self.progress.stop()
        self.run_btn.config(state=tk.NORMAL)
        self.log(f"错误: {error_msg}")
        self.log("="*40)
        messagebox.showerror("运行出错", f"处理过程中发生错误：\n{error_msg}")

if __name__ == "__main__":
    root = tk.Tk()
    app = FitnessGUI(root)
    root.mainloop()
