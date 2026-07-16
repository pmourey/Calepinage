# helper functions for menu actions (imported by editor.py)

def _ask_save_if_dirty(ed):
    if getattr(ed, 'dirty', False):
        if ed._confirm('Projet modifié. Sauvegarder avant ?'):
            # save (ask for name if needed)
            if getattr(ed, 'current_project', None):
                return ed.save_project(ed.current_project)
            else:
                return ed._prompt_save_project()
        # user chose no
    return True
