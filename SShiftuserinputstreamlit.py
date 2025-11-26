────────────────────────────────────────────────────────────────────────────────

NameError: name 'StraddleShiftInput' is not defined

[06:24:49] 🔄 Updated app!

────────────────────── Traceback (most recent call last) ───────────────────────

  /home/adminuser/venv/lib/python3.13/site-packages/streamlit/runtime/scriptru  

  nner/exec_code.py:121 in exec_func_with_error_handling                        

                                                                                

  /home/adminuser/venv/lib/python3.13/site-packages/streamlit/runtime/scriptru  

  nner/script_runner.py:640 in code_to_exec                                     

                                                                                

  /mount/src/straddleshiftclientinputs/SShiftuserinputstreamlit.py:17 in        

  <module>                                                                      

                                                                                

     14 st.set_page_config(page_title="Straddle Shift Strategy Controls CST000  

     15                                                                         

     16                                                                         

  ❱  17 class StraddleShiftInput:                                               

     18 │   # ---------------- Time/Display Constants ----------------          

     19 │   # Allowed trading time window                                       

     20 │   MIN_T = time(9, 15, 0)                                              

                                                                                

  /mount/src/straddleshiftclientinputs/SShiftuserinputstreamlit.py:482 in       

  StraddleShiftInput                                                            

                                                                                

    479                                                                         

    480                                                                         

    481 # ---------------- Main ----------------nif __name__ == "__main__":     

  ❱ 482 │   StraddleShiftInput().run()                                          

    483                                                                         

────────────────────────────────────────────────────────────────────────────────

NameError: name 'StraddleShiftInput' is not defined
