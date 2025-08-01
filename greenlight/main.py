from greenlight.ui import UIBase

op = ""
ui = UIBase()

def main():
    while True:
        ui.splash()
        op = ui.operator_menu()
        if op != "q":
            ui.main_menu(op)
            continue

if __name__ == "__main__":
    main()

