;;; READ-ONLY entity census (acceptance helper, not part of the diagnostics tool).
;;; Writes one tab-separated line per entity of the WHOLE drawing (all layouts) to an external file.
(defun cs:xdata-tag (ed / app tag)
  (foreach app (cdr (assoc -3 ed))
    (foreach v (cdr app)
      (if (and (= (car v) 1000) (= (type (cdr v)) 'STR)) (setq tag (strcat (if tag (strcat tag "|") "") (car app) ":" (cdr v))))))
  (if tag tag ""))
(defun cs:pts (ed / out item)
  (foreach item ed
    (if (member (car item) '(10 11))
      (setq out (strcat (if out (strcat out ";") "")
                        (rtos (cadr item) 2 8) "," (rtos (caddr item) 2 8)))))
  (if out out ""))
(defun cs:run (path / ss i en ed typ f tb)
  (setq ss (ssget "_X") tb (chr 9) i 0)
  (setq f (open path "w" "utf8"))
  (princ (strcat "SSGET_COUNT" tb (itoa (if ss (sslength ss) 0)) (chr 10)) f)
  (if ss
    (repeat (sslength ss)
      (setq en (ssname ss i) ed (entget en '("*")) typ (cdr (assoc 0 ed)))
      (princ (strcat (cdr (assoc 5 ed)) tb typ tb (cdr (assoc 8 ed)) tb
                     (if (assoc 410 ed) (cdr (assoc 410 ed)) "Model") tb
                     (if (= typ "INSERT") (cdr (assoc 2 ed)) "") tb
                     (cs:xdata-tag ed) tb
                     (if (= typ "INSERT")
                       (strcat (rtos (cadr (assoc 10 ed)) 2 8) "," (rtos (caddr (assoc 10 ed)) 2 8) ","
                               (rtos (if (assoc 50 ed) (cdr (assoc 50 ed)) 0.0) 2 10) ","
                               (rtos (if (assoc 41 ed) (cdr (assoc 41 ed)) 1.0) 2 10))
                       (cs:pts ed))
                     (chr 10)) f)
      (setq i (1+ i))))
  (close f)
  (princ))
