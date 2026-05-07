import customtkinter as ctk
app = ctk.CTk()
ctk.CTkButton(app, text="TEST BUTTON").pack(padx=50, pady=50)
app.after(3000, app.destroy)
app.mainloop()
