from greenlight import db, ui
from time import sleep

op = ""

def main():
    while True:
        ui.splash()
        op = ui.operator_menu()
        if op != "q":
            ui.init(op)
            ui.main_menu()
            continue

if __name__ == "__main__":
    main()

