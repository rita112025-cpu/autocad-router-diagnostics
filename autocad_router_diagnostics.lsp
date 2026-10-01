;;; ====================================================================
;;; autocad_router_diagnostics.lsp  --  READ-ONLY Router geometry diagnostics
;;;
;;; Commands (nothing runs on load):
;;;   CTRDIAG        pick ONE Router fitting INSERT -> analyse -> JSON+CSV+TXT
;;;   CTRDIAGALL     analyse every Router fitting / PATH / Straight in the drawing
;;;   CTRDIAGEXPORT  raw data dump only (fittings, PATHs, vertices, XDATA)
;;;
;;; READ-ONLY GUARANTEE: this file never calls entmod / entdel / entmake /
;;; entmakex / command / setvar / regapp / SAVE, no vla-put*, no block or
;;; XDATA changes.  It only uses ssget / entget / entnext / tblobjname /
;;; trans / getvar / read-only ActiveX properties, and writes EXTERNAL files
;;; (JSON, CSV, TXT).  tests/test_readonly_guard.py enforces this statically.
;;;
;;; Source style: no backslash characters anywhere (chr 92 / chr 34 / chr 10
;;; are used instead) so the file survives script transport unchanged.
;;; ====================================================================
(vl-load-com)

(setq ard:version "1.0.0"
      ard:schema-version "1.0")
(setq ard:q (chr 34) ard:bs (chr 92) ard:lf (chr 10))

;;; ---- configuration -------------------------------------------------
(setq ard:out-dir "D:/github/autocad-router-diagnostics/output/")
(setq ard:path-layer "SCADA-TRAY-PATH"
      ard:gen-layer  "SCADA-TRAY"
      ard:app-path   "CTR_PATH"
      ard:app-gen    "CTR_GEN"
      ard:default-profile "DEFAULT"
      ard:default-width   300.0)
;;; fitting type by block-name PATTERN (wcmatch, upper-cased name)
(setq ard:fitting-patterns
  '(("ELBOW" . "*SCADA_TRAY_ELBOW*")
    ("TEE"   . "*SCADA_TRAY_TEE*")
    ("CROSS" . "*SCADA_TRAY_CROSS*")))
(setq ard:fitting-xdata-tags '("ELBOW" "TEE" "CROSS"))

;;; ---- thresholds: every one of them is written into the report --------
(setq ard:th-pt 0.001          ; coordinate coincidence, mm (= Router *CTR-TOL*)
      ard:th-ang 0.0001        ; orthogonality tolerance, rad (= Router *CTR-ANGTOL*)
      ard:th-exact 0.01        ; connection error <= this  -> EXACT, mm
      ard:th-near 1.0          ; connection error <= this  -> NEAR, mm; above -> MISMATCH
      ard:th-corridor 30.0     ; extra half-width around an arm ray when picking geometry, mm
      ard:th-face 0.5          ; end-face band: points within this of the extreme, mm
      ard:th-arc-deg 7.5       ; arc sampling step, degrees
      ard:th-geom-rel 1.0e-5   ; block-geometry tolerance = this * block bbox diagonal (block units)
      ard:th-open-dir-deg 0.5  ; an opening 'faces' an arm when its outward normal is within this angle
      ard:th-cand-max 10)      ; PATH candidates listed per fitting

;;; ---- run state ---------------------------------------------------
(setq ard:run-note nil)   ; optional free text copied into the report (set by test / diagnostic scripts)
(setq ard:*bcache* nil ard:*paths* nil ard:*straights* nil ard:*segs* nil
      ard:*junctions* nil ard:*warnings* nil ard:*files* nil)

;;; ====================================================================
;;; 1. small helpers
;;; ====================================================================
(defun ard:bool (v) (if v T 'ARD_FALSE))
(defun ard:tp (v) (eq v T))   ; truth test for values built with ard:bool
(defun ard:obj (pairs) (cons 'ARD_OBJ pairs))
(defun ard:arr (items) (cons 'ARD_ARR items))
(defun ard:get (key obj) (cdr (assoc key (cdr obj))))
(defun ard:z (p) (if (and (cddr p) (numberp (caddr p))) (float (caddr p)) 0.0))
(defun ard:pt3 (p) (if p (ard:arr (list (float (car p)) (float (cadr p)) (ard:z p))) nil))
(defun ard:d2 (a b / dx dy)
  (setq dx (- (car a) (car b)) dy (- (cadr a) (cadr b)))
  (sqrt (+ (* dx dx) (* dy dy))))
(defun ard:pt-eq (a b) (< (ard:d2 a b) ard:th-pt))
(defun ard:t (v n) (if (numberp v) (rtos v 2 n) "n/a"))
(defun ard:join (strs sep / out first s)
  (setq out "" first T)
  (foreach s strs (setq out (strcat out (if first "" sep) s) first nil))
  out)
(defun ard:str-replace (s old new / p out)
  (setq out "")
  (while (setq p (vl-string-search old s))
    (setq out (strcat out (substr s 1 p) new)
          s (substr s (+ p (strlen old) 1))))
  (strcat out s))
(defun ard:layout (ed) (if (assoc 410 ed) (cdr (assoc 410 ed)) "Model"))
(defun ard:ss->list (ss / i out)
  (setq i 0)
  (if ss
    (repeat (sslength ss)
      (setq out (cons (ssname ss i) out) i (1+ i))))
  (reverse out))
(defun ard:warn (code msg)
  (setq ard:*warnings*
    (cons (ard:obj (list (cons "code" code) (cons "message" msg))) ard:*warnings*)))
(defun ard:unique-strs (strs / out s)
  (foreach s strs (if (not (member s out)) (setq out (cons s out))))
  (reverse out))

;;; ====================================================================
;;; 2. JSON / CSV writers (streaming, external files only)
;;; ====================================================================
(defun ard:hex2 (n / d)
  (setq d "0123456789abcdef")
  (strcat (substr d (1+ (/ n 16)) 1) (substr d (1+ (rem n 16)) 1)))
(defun ard:jstr (s / out i n c code)
  (setq s (if (= (type s) 'STR) s "") out "" i 1 n (strlen s))
  (while (<= i n)
    (setq c (substr s i 1) code (ascii c))
    (setq out
      (strcat out
        (cond ((= code 34) (strcat ard:bs ard:q))
              ((= code 92) (strcat ard:bs ard:bs))
              ((= code 10) (strcat ard:bs "n"))
              ((= code 13) (strcat ard:bs "r"))
              ((= code 9)  (strcat ard:bs "t"))
              ((< code 32) (strcat ard:bs "u00" (ard:hex2 code)))
              (T c))))
    (setq i (1+ i)))
  (strcat ard:q out ard:q))
(defun ard:num (v)
  (cond ((= (type v) 'INT) (itoa v))
        ((= (type v) 'REAL)
         (if (< (abs v) 5.0e-11) "0" (rtos v 2 10)))
        (T "null")))
(defun ard:jw (x f depth / first it)
  (cond
    ((null x) (princ "null" f))
    ((eq x T) (princ "true" f))
    ((eq x 'ARD_FALSE) (princ "false" f))
    ((numberp x) (princ (ard:num x) f))
    ((= (type x) 'STR) (princ (ard:jstr x) f))
    ((and (listp x) (eq (car x) 'ARD_ARR))
     (princ "[" f)
     (setq first T)
     (foreach it (cdr x)
       (if first (setq first nil) (princ "," f))
       (if (< depth 3) (princ ard:lf f))
       (ard:jw it f (1+ depth)))
     (princ "]" f))
    ((and (listp x) (eq (car x) 'ARD_OBJ))
     (princ "{" f)
     (setq first T)
     (foreach it (cdr x)
       (if (/= (substr (car it) 1 1) "_")
         (progn
           (if first (setq first nil) (princ "," f))
           (if (< depth 4) (princ ard:lf f))
           (princ (ard:jstr (car it)) f)
           (princ ":" f)
           (ard:jw (cdr it) f (1+ depth)))))
     (princ "}" f))
    (T (princ "null" f))))
(defun ard:csv-cell (v / s)
  (setq s (cond ((null v) "")
                ((eq v T) "true")
                ((eq v 'ARD_FALSE) "false")
                ((numberp v) (ard:num v))
                ((= (type v) 'STR) v)
                (T "")))
  (if (or (vl-string-search "," s) (vl-string-search ard:q s)
          (vl-string-search ard:lf s) (vl-string-search (chr 13) s)
          (and (> (strlen s) 0)
               (or (= (substr s 1 1) " ") (= (substr s (strlen s) 1) " "))))
    (strcat ard:q (ard:str-replace s ard:q (strcat ard:q ard:q)) ard:q)
    s))
(defun ard:csv-row (cells / out first c)
  (setq out "" first T)
  (foreach c cells (setq out (strcat out (if first "" ",") (ard:csv-cell c)) first nil))
  out)

;;; ====================================================================
;;; 3. entity readers (read-only)
;;; ====================================================================
(defun ard:xapp (ed name / hit app)
  (foreach app (cdr (assoc -3 ed))
    (if (and (null hit) (= (strcase (car app)) (strcase name)))
      (setq hit (cdr app))))
  hit)
(defun ard:xdata-raw (ed / out app v val)
  (foreach app (cdr (assoc -3 ed))
    (foreach v (cdr app)
      (setq val (cdr v))
      (setq out
        (cons
          (ard:obj
            (list (cons "app" (car app)) (cons "code" (car v))
                  (cons "value"
                    (if (and val (listp val))
                      (ard:arr (mapcar 'float val))
                      val))))
          out))))
  (ard:arr (reverse out)))
(defun ard:gen-tag (ed / hit item)
  (foreach item (ard:xapp ed ard:app-gen)
    (if (and (null hit) (= (car item) 1000) (= (type (cdr item)) 'STR))
      (setq hit (cdr item))))
  hit)
;;; Router schema (cable_tray_router.lsp ctr-make-path / ctr-get-path):
;;;   CTR_PATH: (1000 . "PATH") (1040 . width) (1000 . "PROFILE=<name>")
;;;   missing -> profile DEFAULT, width 300.
(defun ard:path-attrs (ed / xd item s prof w pe we)
  (setq xd (ard:xapp ed ard:app-path) prof ard:default-profile w ard:default-width)
  (foreach item xd
    (cond
      ((= (car item) 1040) (setq w (float (cdr item)) we T))
      ((and (= (car item) 1000) (= (type (cdr item)) 'STR)
            (>= (strlen (cdr item)) 8) (= (substr (cdr item) 1 8) "PROFILE="))
       (setq prof (substr (cdr item) 9) pe T))))
  (list prof w pe we (if xd T nil)))
(defun ard:line-verts (ed / a b)
  (setq a (cdr (assoc 10 ed)) b (cdr (assoc 11 ed)))
  (list (list (float (car a)) (float (cadr a)) (ard:z a) 0.0)
        (list (float (car b)) (float (cadr b)) (ard:z b) 0.0)))
;;; LWPOLYLINE vertices in WCS: (x y z bulge)
(defun ard:lw-verts (en ed / elev out cur item p)
  (setq elev (if (assoc 38 ed) (cdr (assoc 38 ed)) 0.0))
  (foreach item ed
    (cond
      ((= (car item) 10)
       (if cur (setq out (cons cur out)))
       (setq p (trans (list (cadr item) (caddr item) elev) en 0))
       (setq cur (list (float (car p)) (float (cadr p)) (float (caddr p)) 0.0)))
      ((and (= (car item) 42) cur)
       (setq cur (list (car cur) (cadr cur) (caddr cur) (float (cdr item)))))))
  (if cur (setq out (cons cur out)))
  (reverse out))
(defun ard:verts-json (verts typ / i out v)
  (setq i 0)
  (foreach v verts
    (setq out
      (cons
        (ard:obj
          (append
            (list (cons "index" i) (cons "x" (car v)) (cons "y" (cadr v)) (cons "z" (caddr v)))
            (if (= typ "LWPOLYLINE") (list (cons "bulge" (cadddr v))) nil)))
        out))
    (setq i (1+ i)))
  (ard:arr (reverse out)))
(defun ard:closed-p (typ ed)
  (and (= typ "LWPOLYLINE") (assoc 70 ed) (= 1 (logand 1 (cdr (assoc 70 ed))))))
(defun ard:verts-of (en ed typ)
  (if (= typ "LINE") (ard:line-verts ed) (ard:lw-verts en ed)))

(defun ard:make-path (en / ed typ verts attrs cl bulge v)
  (setq ed (entget en '("*")) typ (cdr (assoc 0 ed)))
  (setq verts (ard:verts-of en ed typ) attrs (ard:path-attrs ed) cl (ard:closed-p typ ed))
  (foreach v verts (if (> (abs (cadddr v)) 1.0e-9) (setq bulge T)))
  (ard:obj
    (list (cons "entity_type" typ) (cons "handle" (cdr (assoc 5 ed)))
          (cons "layer" (cdr (assoc 8 ed))) (cons "layout" (ard:layout ed))
          (cons "closed" (ard:bool cl))
          (cons "profile" (car attrs)) (cons "width" (cadr attrs))
          (cons "profile_explicit" (ard:bool (caddr attrs)))
          (cons "width_explicit" (ard:bool (cadddr attrs)))
          (cons "has_ctr_path_xdata" (ard:bool (nth 4 attrs)))
          (cons "has_bulge" (ard:bool bulge))
          (cons "vertex_count" (length verts))
          (cons "xdata_raw" (ard:xdata-raw ed))
          (cons "vertices" (ard:verts-json verts typ))
          (cons "_verts" verts) (cons "_closed" cl))))
(defun ard:make-straight (en ed / typ verts cl)
  (setq typ (cdr (assoc 0 ed)) verts (ard:verts-of en ed typ) cl (ard:closed-p typ ed))
  (ard:obj
    (list (cons "entity_type" typ) (cons "handle" (cdr (assoc 5 ed)))
          (cons "layer" (cdr (assoc 8 ed))) (cons "layout" (ard:layout ed))
          (cons "closed" (ard:bool cl))
          (cons "generated_tag" (ard:gen-tag ed))
          (cons "vertex_count" (length verts))
          (cons "xdata_raw" (ard:xdata-raw ed))
          (cons "vertices" (ard:verts-json verts typ))
          (cons "_verts" verts))))

(defun ard:scan-paths (/ ss all out en typ cnt cell p)
  (setq ss (ssget "_X" (list (cons 0 "LINE,LWPOLYLINE") (cons 8 ard:path-layer))))
  (foreach en (ard:ss->list ss) (setq out (cons (ard:make-path en) out)))
  (setq all (ssget "_X" (list (cons 8 ard:path-layer))))
  (foreach en (ard:ss->list all)
    (setq typ (cdr (assoc 0 (entget en))))
    (if (not (member typ '("LINE" "LWPOLYLINE")))
      (if (setq cell (assoc typ cnt))
        (setq cnt (subst (cons typ (1+ (cdr cell))) cell cnt))
        (setq cnt (cons (cons typ 1) cnt)))))
  (foreach p out
    (if (ard:tp (ard:get "has_bulge" p))
      (ard:warn "ARC_SEGMENT_TREATED_AS_CHORD"
        (strcat "PATH " (ard:get "handle" p) " has a bulge (arc) segment; topology uses the chord (Router rejects such paths)"))))
  (foreach cell cnt
    (ard:warn "UNSUPPORTED_PATH_ENTITY"
      (strcat (itoa (cdr cell)) " " (car cell) " entity(ies) on layer " ard:path-layer
              " ignored (only LINE / LWPOLYLINE are read)")))
  (reverse out))
(defun ard:scan-straights (/ ss out en ed)
  (setq ss (ssget "_X" (list (cons 0 "LINE,LWPOLYLINE") (cons 8 ard:gen-layer))))
  (foreach en (ard:ss->list ss)
    (setq ed (entget en '("*")))
    (if (= (ard:gen-tag ed) "STRAIGHT")
      (setq out (cons (ard:make-straight en ed) out))))
  (reverse out))

;;; ====================================================================
;;; 4. block-definition geometry (world points of a fitting)
;;; ====================================================================
;;; affine matrix (a b c d tx ty):  x' = a x + c y + tx ;  y' = b x + d y + ty
(defun ard:mat-apply (m p)
  (list (+ (* (nth 0 m) (car p)) (* (nth 2 m) (cadr p)) (nth 4 m))
        (+ (* (nth 1 m) (car p)) (* (nth 3 m) (cadr p)) (nth 5 m))))
(defun ard:mat-mul (m1 m2)
  (list (+ (* (nth 0 m1) (nth 0 m2)) (* (nth 2 m1) (nth 1 m2)))
        (+ (* (nth 1 m1) (nth 0 m2)) (* (nth 3 m1) (nth 1 m2)))
        (+ (* (nth 0 m1) (nth 2 m2)) (* (nth 2 m1) (nth 3 m2)))
        (+ (* (nth 1 m1) (nth 2 m2)) (* (nth 3 m1) (nth 3 m2)))
        (+ (* (nth 0 m1) (nth 4 m2)) (* (nth 2 m1) (nth 5 m2)) (nth 4 m1))
        (+ (* (nth 1 m1) (nth 4 m2)) (* (nth 3 m1) (nth 5 m2)) (nth 5 m1))))
(defun ard:block-base (name / be)
  (setq be (tblobjname "BLOCK" name))
  (if be (cdr (assoc 10 (entget be))) (list 0.0 0.0 0.0)))
;;; INSERT entity data -> matrix from block space to container space
(defun ard:insert-matrix (ed / ip sx sy rot base)
  (setq ip (cdr (assoc 10 ed))
        sx (if (assoc 41 ed) (cdr (assoc 41 ed)) 1.0)
        sy (if (assoc 42 ed) (cdr (assoc 42 ed)) 1.0)
        rot (if (assoc 50 ed) (cdr (assoc 50 ed)) 0.0)
        base (ard:block-base (cdr (assoc 2 ed))))
  (ard:mat-mul
    (list (* sx (cos rot)) (* sx (sin rot)) (- (* sy (sin rot))) (* sy (cos rot))
          (float (car ip)) (float (cadr ip)))
    (list 1.0 0.0 0.0 1.0 (- (car base)) (- (cadr base)))))
(defun ard:arc-pts (cx cy r a0 theta m / n k pts ang c d step)
  ;; theta signed sweep (rad) from a0; samples + endpoints + cardinal extremes
  (setq step (* ard:th-arc-deg (/ pi 180.0)))
  (setq n (max 4 (fix (+ 0.999999 (/ (abs theta) step)))))
  (setq k 0)
  (while (<= k n)
    (setq ang (+ a0 (* theta (/ (float k) n))))
    (setq pts (cons (ard:mat-apply m (list (+ cx (* r (cos ang))) (+ cy (* r (sin ang))))) pts))
    (setq k (1+ k)))
  (foreach c (list 0.0 (/ pi 2.0) pi (* 1.5 pi))
    (setq d (if (>= theta 0.0) (- c a0) (- a0 c)))
    (while (< d 0.0) (setq d (+ d (* 2.0 pi))))
    (while (>= d (* 2.0 pi)) (setq d (- d (* 2.0 pi))))
    (if (< d (abs theta))
      (setq pts (cons (ard:mat-apply m (list (+ cx (* r (cos c))) (+ cy (* r (sin c))))) pts))))
  pts)
(defun ard:bulge-pts (p1 p2 b m / dx dy len h nx ny mx my cx cy r a0 theta)
  (setq dx (- (car p2) (car p1)) dy (- (cadr p2) (cadr p1)) len (sqrt (+ (* dx dx) (* dy dy))))
  (if (or (< len 1.0e-12) (< (abs b) 1.0e-9))
    (list (ard:mat-apply m p1) (ard:mat-apply m p2))
    (progn
      (setq h (* (/ len 2.0) (/ (- 1.0 (* b b)) (* 2.0 b)))
            nx (/ (- dy) len) ny (/ dx len)
            mx (/ (+ (car p1) (car p2)) 2.0) my (/ (+ (cadr p1) (cadr p2)) 2.0)
            cx (+ mx (* nx h)) cy (+ my (* ny h))
            r (ard:d2 (list cx cy) p1)
            a0 (atan (- (cadr p1) cy) (- (car p1) cx))
            theta (* 4.0 (atan b)))
      (ard:arc-pts cx cy r a0 theta m))))
(defun ard:note-arc (c r / cell)
  (setq cell (vl-some '(lambda (x) (if (< (ard:d2 (car x) c) 0.001) x nil)) ard:*ga*))
  (if cell
    (if (not (member r (cdr cell)))
      (setq ard:*ga* (subst (cons (car cell) (append (cdr cell) (list r))) cell ard:*ga*)))
    (setq ard:*ga* (append ard:*ga* (list (list c r))))))
(defun ard:note-seg (p q)
  (setq ard:*gl* (cons (list (list (car p) (cadr p)) (list (car q) (cadr q))) ard:*gl*)))
(defun ard:note-arc-rec (m c r a0 a1 / k rot)
  (setq k (sqrt (+ (* (nth 0 m) (nth 0 m)) (* (nth 1 m) (nth 1 m))))
        rot (atan (nth 1 m) (nth 0 m)))
  (setq ard:*gr* (cons (list (ard:mat-apply m c) (* r k) (+ a0 rot) (+ a1 rot)) ard:*gr*)))
(defun ard:tally (key / cell)
  (if (setq cell (assoc key ard:*gs*))
    (setq ard:*gs* (subst (cons key (1+ (cdr cell))) cell ard:*gs*))
    (setq ard:*gs* (cons (cons key 1) ard:*gs*))))
(defun ard:curve-pts (en m / s0 s1 k n pts p)
  (setq s0 (vl-catch-all-apply 'vlax-curve-getStartParam (list en))
        s1 (vl-catch-all-apply 'vlax-curve-getEndParam (list en)))
  (if (or (vl-catch-all-error-p s0) (vl-catch-all-error-p s1))
    (progn (ard:tally "UNSUPPORTED_CURVE") nil)
    (progn
      (setq n 32 k 0)
      (while (<= k n)
        (setq p (vl-catch-all-apply 'vlax-curve-getPointAtParam
                  (list en (+ s0 (* (- s1 s0) (/ (float k) n))))))
        (if (and p (not (vl-catch-all-error-p p)))
          (setq pts (cons (ard:mat-apply m p) pts)))
        (setq k (1+ k)))
      pts)))
(defun ard:lw-raw (ed / out cur item)
  (foreach item ed
    (cond
      ((= (car item) 10)
       (if cur (setq out (cons cur out)))
       (setq cur (list (float (cadr item)) (float (caddr item)) 0.0)))
      ((and (= (car item) 42) cur)
       (setq cur (list (car cur) (cadr cur) (float (cdr item)))))))
  (if cur (setq out (cons cur out)))
  (reverse out))
(defun ard:ent-pts (en ed m depth / typ pts v prev a0 a1 c r th)
  (setq typ (cdr (assoc 0 ed)))
  (cond
    ((= typ "LINE")
     (ard:tally typ)
     (ard:note-seg (ard:mat-apply m (cdr (assoc 10 ed))) (ard:mat-apply m (cdr (assoc 11 ed))))
     (list (ard:mat-apply m (cdr (assoc 10 ed))) (ard:mat-apply m (cdr (assoc 11 ed)))))
    ((= typ "LWPOLYLINE")
     (ard:tally typ)
     (setq v (ard:lw-raw ed))
     (foreach c v
       (if prev
         (progn
           (setq pts (append (ard:bulge-pts prev c (caddr prev) m) pts))
           (if (< (abs (caddr prev)) 1.0e-9) (ard:note-seg (ard:mat-apply m prev) (ard:mat-apply m c)))))
       (setq prev c))
     (if (and prev (cdr v) (= 1 (logand 1 (if (assoc 70 ed) (cdr (assoc 70 ed)) 0))))
       (progn
         (setq pts (append (ard:bulge-pts prev (car v) (caddr prev) m) pts))
         (if (< (abs (caddr prev)) 1.0e-9) (ard:note-seg (ard:mat-apply m prev) (ard:mat-apply m (car v))))))
     (if (and v (null (cdr v))) (setq pts (list (ard:mat-apply m (car v)))))
     pts)
    ((= typ "ARC")
     (ard:tally typ)
     (ard:note-arc (ard:mat-apply m (cdr (assoc 10 ed))) (cdr (assoc 40 ed)))
     (setq c (cdr (assoc 10 ed)) r (cdr (assoc 40 ed))
           a0 (cdr (assoc 50 ed)) a1 (cdr (assoc 51 ed)) th (- a1 a0))
     (ard:note-arc-rec m c r a0 a1)
     (while (<= th 0.0) (setq th (+ th (* 2.0 pi))))
     (ard:arc-pts (car c) (cadr c) r a0 th m))
    ((= typ "CIRCLE")
     (ard:tally typ)
     (setq c (cdr (assoc 10 ed)) r (cdr (assoc 40 ed)))
     (ard:arc-pts (car c) (cadr c) r 0.0 (* 2.0 pi) m))
    ((member typ '("SPLINE" "ELLIPSE"))
     (ard:tally typ)
     (ard:curve-pts en m))
    ((= typ "INSERT")
     (ard:tally typ)
     (if (< depth 3)
       (ard:block-pts (cdr (assoc 2 ed)) (ard:mat-mul m (ard:insert-matrix ed)) (1+ depth))
       (progn (ard:tally "NESTED_TOO_DEEP") nil)))
    (T (ard:tally (strcat "IGNORED:" typ)) nil)))
(defun ard:block-pts (name m depth / be en ed pts)
  (setq be (tblobjname "BLOCK" name))
  (if be
    (progn
      (setq en (entnext be))
      (while en
        (setq ed (entget en))
        (if (= (cdr (assoc 0 ed)) "ENDBLK")
          (setq en nil)
          (progn
            (setq pts (append (ard:ent-pts en ed m depth) pts))
            (setq en (entnext en)))))
      pts)
    nil))
;;; -> (block-found local-points tally arc-centres straight-segments arc-records openings joint); cached per block name
(defun ard:block-local (name / hit ard:*gs* ard:*ga* ard:*gl* ard:*gr* pts found segs ops)
  (if (setq hit (assoc name ard:*bcache*))
    (cdr hit)
    (progn
      (setq ard:*gs* nil ard:*ga* nil ard:*gl* nil ard:*gr* nil found (if (tblobjname "BLOCK" name) T nil))
      (setq pts (if found (ard:block-pts name (list 1.0 0.0 0.0 1.0 0.0 0.0) 0) nil))
      (setq segs (ard:dedupe-segs (reverse ard:*gl*) (ard:geom-tol pts)))
      (setq ops (ard:derive-openings segs pts))
      (setq hit (list found pts ard:*gs* ard:*ga* segs (reverse ard:*gr*) ops (ard:axis-joint ops)))
      (setq ard:*bcache* (cons (cons name hit) ard:*bcache*))
      hit)))
;;; ====================================================================
;;; 4b. cable-tray OPENINGS derived from block geometry (no hard-coded sizes)
;;;
;;; An opening is where a tray arm ends.  It is recognised from geometry evidence only:
;;;   * two CAP segments: equal length, collinear, separated by a gap wider than the cap
;;;     (the two rail end edges),
;;;   * each cap endpoint is attached to a perpendicular RAIL EDGE running to the same side,
;;;   * nothing of the block lies beyond the cap line inside the strip spanned by the caps.
;;; Per opening (block coordinates): for each rail the outer edge (extreme endpoint of the cap),
;;; the inner edge (the other endpoint) and the rail centre (their midpoint); the opening centre is
;;; the midpoint of the two rail centres; the outward normal points away from the rails.
;;; The farthest point of the block is NEVER used.
;;; ====================================================================
(defun ard:vdot (a b) (+ (* (car a) (car b)) (* (cadr a) (cadr b))))
(defun ard:vlen (a) (sqrt (ard:vdot a a)))
(defun ard:vsub (a b) (list (- (car a) (car b)) (- (cadr a) (cadr b))))
(defun ard:vunit (a / l) (setq l (ard:vlen a)) (if (< l 1.0e-12) nil (list (/ (car a) l) (/ (cadr a) l))))
(defun ard:vperp (u) (list (- (cadr u)) (car u)))
(defun ard:vpt (o u s) (list (+ (car o) (* (car u) s)) (+ (cadr o) (* (cadr u) s))))
(defun ard:geom-tol (pts / bb diag)
  (setq bb (ard:bbox-of pts))
  (setq diag (if bb (ard:d2 (car bb) (cadr bb)) 1.0))
  (max 1.0e-9 (* ard:th-geom-rel diag)))
(defun ard:dedupe-segs (segs tol / out s hit o)
  (foreach s segs
    (setq hit nil)
    (foreach o out
      (if (or (and (< (ard:d2 (car s) (car o)) tol) (< (ard:d2 (cadr s) (cadr o)) tol))
              (and (< (ard:d2 (car s) (cadr o)) tol) (< (ard:d2 (cadr s) (car o)) tol)))
        (setq hit T)))
    (if (and (not hit) (> (ard:d2 (car s) (cadr s)) tol)) (setq out (cons s out))))
  (reverse out))
;;; signed extents (along n) of segments that touch pt and run perpendicular to u
(defun ard:attached (pt segs skip u n tol / out s far d l)
  (foreach s segs
    (if (not (member s skip))
      (progn
        (setq far (cond ((< (ard:d2 (car s) pt) tol) (cadr s))
                        ((< (ard:d2 (cadr s) pt) tol) (car s))
                        (T nil)))
        (if far
          (progn
            (setq d (ard:vsub far pt) l (ard:vlen d))
            (if (and (> l tol) (< (/ (abs (ard:vdot d u)) l) 1.0e-3))
              (setq out (cons (ard:vdot d n) out))))))))
  out)
(defun ard:same-side (exts / sg ok e)
  ;; every attached extent must lie on one side; returns +1 / -1 / nil
  (setq ok T)
  (foreach e exts
    (if (null sg)
      (setq sg (if (> e 0.0) 1.0 -1.0))
      (if (/= sg (if (> e 0.0) 1.0 -1.0)) (setq ok nil))))
  (if ok sg nil))
(defun ard:make-opening (o u n sv side / s1 s2 s3 s4 outw ss)
  ;; sv = the 4 cap endpoint coordinates along u (from origin o)
  (setq ss (vl-sort sv '<) s1 (nth 0 ss) s2 (nth 1 ss) s3 (nth 2 ss) s4 (nth 3 ss))
  (setq outw (ard:vunit (list (* (- side) (car n)) (* (- side) (cadr n)))))
  (list (cons "center" (ard:vpt o u (/ (+ s1 s2 s3 s4) 4.0)))
        (cons "normal" outw)
        (cons "u" u)
        (cons "rails"
          (list (list (ard:vpt o u s1) (ard:vpt o u s2) (ard:vpt o u (/ (+ s1 s2) 2.0)))
                (list (ard:vpt o u s4) (ard:vpt o u s3) (ard:vpt o u (/ (+ s3 s4) 2.0)))))
        (cons "width_center_to_center" (/ (- (+ s3 s4) (+ s1 s2)) 2.0))
        (cons "width_outer" (- s4 s1))
        (cons "width_inner" (- s3 s2))
        (cons "cap_length" (- s2 s1))))
(defun ard:opening-angle (op / nv a)
  (setq nv (cdr (assoc "normal" op)) a (atan (cadr nv) (car nv)))
  (if (< a 0.0) (+ a (* 2.0 pi)) a))
(defun ard:derive-openings (sg pts / tol tl tc n i j si sj li lj ui nn o sj1 sj2 lo hi gap
                                      ends exts side ok sv smin smax p d sp op ops dup q k)
  (setq tol (ard:geom-tol pts) tl (* 20.0 tol) tc (* 5.0 tol) n (length sg))
  (setq i 0)
  (while (< i n)
    (setq si (nth i sg) li (ard:d2 (car si) (cadr si)) ui (ard:vunit (ard:vsub (cadr si) (car si))))
    (setq nn (ard:vperp ui) o (car si) j (1+ i))
    (while (< j n)
      (setq sj (nth j sg) lj (ard:d2 (car sj) (cadr sj)))
      (if (and (< (abs (- li lj)) tl)
               (< (abs (ard:vdot (ard:vsub (car sj) o) nn)) tc)
               (< (abs (ard:vdot (ard:vsub (cadr sj) o) nn)) tc))
        (progn
          (setq sj1 (ard:vdot (ard:vsub (car sj) o) ui) sj2 (ard:vdot (ard:vsub (cadr sj) o) ui)
                lo (min sj1 sj2) hi (max sj1 sj2)
                gap (max (- lo li) (- hi)))
          (if (> gap li)
            (progn
              (setq ends (list (car si) (cadr si) (car sj) (cadr sj)) exts nil ok T)
              (foreach p ends
                (setq k (ard:attached p sg (list si sj) ui nn tc))
                (if k (setq exts (append k exts)) (setq ok nil)))
              (setq side (if ok (ard:same-side exts) nil))
              (if side
                (progn
                  (setq sv (list 0.0 li sj1 sj2) smin (apply 'min sv) smax (apply 'max sv))
                  (setq op (ard:make-opening o ui nn sv side))
                  (foreach p pts
                    (setq d (ard:vdot (ard:vsub p o) (cdr (assoc "normal" op)))
                          sp (ard:vdot (ard:vsub p o) ui))
                    (if (and (> d tc) (>= sp (- smin tc)) (<= sp (+ smax tc))) (setq ok nil)))
                  (if ok
                    (progn
                      (setq dup nil)
                      (foreach q ops
                        (if (and (< (ard:d2 (cdr (assoc "center" q)) (cdr (assoc "center" op))) tc)
                                 (< (ard:d2 (cdr (assoc "normal" q)) (cdr (assoc "normal" op))) 1.0e-6))
                          (setq dup T)))
                      (if (not dup) (setq ops (cons op ops)))))))))))
      (setq j (1+ j)))
    (setq i (1+ i)))
  (setq ops (vl-sort ops '(lambda (a b) (< (ard:opening-angle a) (ard:opening-angle b)))))
  (setq i 0)
  (setq ops (mapcar '(lambda (op) (setq i (1+ i)) (cons (cons "id" (strcat "O" (itoa i))) op)) ops))
  (mapcar '(lambda (op / cnt)
             (setq cnt 0)
             (foreach q ops
               (if (and (< (ard:d2 (cdr (assoc "normal" q)) (cdr (assoc "normal" op))) 1.0e-6)
                        (< (abs (- (ard:vdot (cdr (assoc "center" q)) (cdr (assoc "normal" q)))
                                   (ard:vdot (cdr (assoc "center" op)) (cdr (assoc "normal" op))))) tc))
                 (setq cnt (1+ cnt))))
             (if (> cnt 1) (cons (cons "ambiguous" T) op) op))
          ops))
;;; least-squares point closest to all opening axes (centre + t * normal); -> (pt rms) or nil
(defun ard:axis-joint (ops / sxx sxy syy bx by op nv c det x y rms cnt dd)
  (if (< (length ops) 2)
    nil
    (progn
      (setq sxx 0.0 sxy 0.0 syy 0.0 bx 0.0 by 0.0)
      (foreach op ops
        (setq nv (cdr (assoc "normal" op)) c (cdr (assoc "center" op)) dd (ard:vdot nv c))
        (setq sxx (+ sxx (- 1.0 (* (car nv) (car nv)))) sxy (- sxy (* (car nv) (cadr nv)))
              syy (+ syy (- 1.0 (* (cadr nv) (cadr nv))))
              bx (+ bx (- (car c) (* (car nv) dd))) by (+ by (- (cadr c) (* (cadr nv) dd)))))
      (setq det (- (* sxx syy) (* sxy sxy)))
      (if (< (abs det) 1.0e-9)
        nil
        (progn
          (setq x (/ (- (* syy bx) (* sxy by)) det) y (/ (- (* sxx by) (* sxy bx)) det))
          (setq rms 0.0 cnt 0)
          (foreach op ops
            (setq nv (cdr (assoc "normal" op)) c (cdr (assoc "center" op)))
            (setq rms (+ rms (expt (ard:vdot (ard:vperp nv) (ard:vsub (list x y) c)) 2)) cnt (1+ cnt)))
          (list (list x y) (sqrt (/ rms cnt))))))))

(defun ard:bbox-of (pts / xs ys)
  (if pts
    (progn
      (setq xs (mapcar 'car pts) ys (mapcar 'cadr pts))
      (list (list (apply 'min xs) (apply 'min ys)) (list (apply 'max xs) (apply 'max ys)))
      )
    nil))
(defun ard:sa->list (x / r)
  ;; full AutoCAD hands back a safearray, other hosts a variant: accept both, never raise
  (setq r (vl-catch-all-apply
            '(lambda ()
               (if (= (type x) 'VARIANT) (setq x (vlax-variant-value x)))
               (vlax-safearray->list x))
            nil))
  (if (vl-catch-all-error-p r) nil r))
(defun ard:activex-bbox (en / ob mn mx r a b)
  (setq ob (vl-catch-all-apply 'vlax-ename->vla-object (list en)))
  (if (vl-catch-all-error-p ob)
    nil
    (progn
      (setq r (vl-catch-all-apply '(lambda () (vla-getboundingbox ob 'mn 'mx) T) nil))
      (if (or (vl-catch-all-error-p r) (null mn) (null mx))
        nil
        (progn
          (setq a (ard:sa->list mn) b (ard:sa->list mx))
          (if (and a b) (list a b) nil))))))
(defun ard:effective-name (en / ob r)
  (setq ob (vl-catch-all-apply 'vlax-ename->vla-object (list en)))
  (if (vl-catch-all-error-p ob)
    nil
    (progn
      (setq r (vl-catch-all-apply 'vlax-get-property (list ob 'EffectiveName)))
      (if (or (vl-catch-all-error-p r) (/= (type r) 'STR)) nil r))))

;;; ====================================================================
;;; 5. fitting records
;;; ====================================================================
(defun ard:kind-from-name (name / u r p)
  (setq u (strcase (if name name "")))
  (foreach p ard:fitting-patterns
    (if (and (null r) (wcmatch u (cdr p))) (setq r (car p))))
  r)
;;; -> (type source effective-name) or nil
(defun ard:fitting-kind (ed en / raw k eff tag)
  (setq raw (cdr (assoc 2 ed)) k (ard:kind-from-name raw))
  (if k
    (list k "block_name" nil)
    (progn
      (setq eff (ard:effective-name en))
      (setq k (if eff (ard:kind-from-name eff) nil))
      (if k
        (list k "effective_name" eff)
        (progn
          (setq tag (ard:gen-tag ed))
          (if (member tag ard:fitting-xdata-tags) (list tag "xdata_tag" eff) nil))))))
(defun ard:stem-of (name / p)
  (setq p (vl-string-position 124 name nil T))
  (if p (substr name (+ p 2)) name))
(defun ard:profile-prefix (name / stem p)
  (setq stem (ard:stem-of name) p (vl-string-search "$" stem))
  (if p (substr stem 1 p) nil))
(defun ard:make-fitting (en / ed kind raw eff ip sc rot ext m bl pts wpts bb bbsrc)
  (setq ed (entget en '("*")) kind (ard:fitting-kind ed en) raw (cdr (assoc 2 ed)))
  (setq eff (if (nth 2 kind) (nth 2 kind) (ard:effective-name en)))
  (setq ip (trans (cdr (assoc 10 ed)) en 0)
        sc (list (if (assoc 41 ed) (cdr (assoc 41 ed)) 1.0)
                 (if (assoc 42 ed) (cdr (assoc 42 ed)) 1.0)
                 (if (assoc 43 ed) (cdr (assoc 43 ed)) 1.0))
        rot (if (assoc 50 ed) (cdr (assoc 50 ed)) 0.0)
        ext (if (assoc 210 ed) (cdr (assoc 210 ed)) (list 0.0 0.0 1.0)))
  (setq m (ard:insert-matrix ed) bl (ard:block-local raw))
  (setq pts (cadr bl) wpts (mapcar '(lambda (p) (ard:mat-apply m p)) pts))
  (setq bb (ard:activex-bbox en) bbsrc "activex")
  (if (null bb)
    (progn
      (setq bb (ard:bbox-of wpts) bbsrc (if bb "computed_from_block_definition" "unavailable"))
      (if bb (setq bb (list (append (car bb) (list (float (caddr ip))))
                            (append (cadr bb) (list (float (caddr ip)))))))))
  (ard:obj
    (list (cons "entity_type" "INSERT") (cons "handle" (cdr (assoc 5 ed)))
          (cons "raw_block_name" raw) (cons "effective_name" eff)
          (cons "resolved_profile_prefix" (ard:profile-prefix raw))
          (cons "profile" (ard:profile-of raw))
          (cons "fitting_type" (car kind)) (cons "fitting_type_source" (cadr kind))
          (cons "insert_x" (float (car ip))) (cons "insert_y" (float (cadr ip)))
          (cons "insert_z" (ard:z ip))
          (cons "scale_x" (float (car sc))) (cons "scale_y" (float (cadr sc)))
          (cons "scale_z" (float (caddr sc)))
          (cons "rotation_rad" (float rot))
          (cons "rotation_deg" (* (float rot) (/ 180.0 pi)))
          (cons "extrusion" (ard:pt3 ext))
          (cons "layer" (cdr (assoc 8 ed))) (cons "layout" (ard:layout ed))
          (cons "bounding_box_min" (if bb (ard:pt3 (car bb)) nil))
          (cons "bounding_box_max" (if bb (ard:pt3 (cadr bb)) nil))
          (cons "bounding_box_source" bbsrc)
          (cons "block_definition_found" (ard:bool (car bl)))
          (cons "block_geometry_point_count" (length pts))
          (cons "block_geometry_tally"
                (ard:obj (mapcar '(lambda (c) (cons (car c) (cdr c))) (reverse (caddr bl)))))
          (cons "block_bbox_local"
                (ard:bb-json (ard:bbox-of pts)))
          (cons "block_arc_centres"
                (ard:arr (mapcar '(lambda (a)
                  (ard:obj (list (cons "x" (car (car a))) (cons "y" (cadr (car a)))
                                 (cons "radii" (ard:arr (cdr a))))))
                  (ard:take (nth 3 bl) 8))))
          (cons "xdata_raw" (ard:xdata-raw ed))
          (cons "_en" en) (cons "_pts" wpts) (cons "_matrix" m)
          (cons "_scale" sc) (cons "_rot" rot) (cons "_ip" ip)
          (cons "_base" (ard:block-base raw)) (cons "_ext" ext))))
(defun ard:profile-of (raw / p)
  (setq p (ard:profile-prefix raw))
  (if p p ard:default-profile))
(defun ard:bb-json (bb)
  (if bb
    (ard:obj (list (cons "min" (ard:pt3 (car bb))) (cons "max" (ard:pt3 (cadr bb)))))
    nil))

(defun ard:scan-fittings (/ ss1 ss2 ens out en ed)
  (setq ss1 (ssget "_X" (list (cons 0 "INSERT") (cons 2 "*SCADA_TRAY_*")))
        ss2 (ssget "_X" (list (cons 0 "INSERT") (cons 8 ard:gen-layer))))
  (foreach en (append (ard:ss->list ss1) (ard:ss->list ss2))
    (if (not (member en ens))
      (progn
        (setq ens (cons en ens) ed (entget en '("*")))
        (if (ard:fitting-kind ed en)
          (setq out (cons (ard:make-fitting en) out))))))
  (reverse out))

;;; ====================================================================
;;; 6. PATH topology (from actual coordinates only; per layout)
;;; ====================================================================
;;; segment: (a b handle profile width layout) ; a,b = (x y z)
(defun ard:path-segs (path / v prev out lay p)
  (setq v (ard:get "_verts" path) lay (ard:get "layout" path))
  (setq prev (car v))
  (foreach p (cdr v)
    (if (> (ard:d2 prev p) ard:th-pt)
      (setq out (cons (list prev p (ard:get "handle" path) (ard:get "profile" path)
                            (ard:get "width" path) lay) out)))
    (setq prev p))
  (if (and (ard:get "_closed" path) (> (length v) 2)
           (> (ard:d2 (last v) (car v)) ard:th-pt))
    (setq out (cons (list (last v) (car v) (ard:get "handle" path) (ard:get "profile" path)
                          (ard:get "width" path) lay) out)))
  (reverse out))
(defun ard:seg-nearest (p a b / dx dy l2 tt qx qy)
  (setq dx (- (car b) (car a)) dy (- (cadr b) (cadr a)) l2 (+ (* dx dx) (* dy dy)))
  (setq tt (if (< l2 1.0e-18) 0.0
             (/ (+ (* (- (car p) (car a)) dx) (* (- (cadr p) (cadr a)) dy)) l2)))
  (setq tt (max 0.0 (min 1.0 tt)))
  (setq qx (+ (car a) (* tt dx)) qy (+ (cadr a) (* tt dy)))
  (list (ard:d2 p (list qx qy))
        (list qx qy (+ (ard:z a) (* tt (- (ard:z b) (ard:z a)))))
        tt))
;;; proper crossing strictly inside both segments (endpoint contacts are vertices)
(defun ard:seg-cross (s o / a b c d rx ry sx sy den qpx qpy tt uu lr ls)
  (setq a (car s) b (cadr s) c (car o) d (cadr o)
        rx (- (car b) (car a)) ry (- (cadr b) (cadr a))
        sx (- (car d) (car c)) sy (- (cadr d) (cadr c))
        den (- (* rx sy) (* ry sx)))
  (if (< (abs den) 1.0e-12)
    nil
    (progn
      (setq qpx (- (car c) (car a)) qpy (- (cadr c) (cadr a))
            tt (/ (- (* qpx sy) (* qpy sx)) den)
            uu (/ (- (* qpx ry) (* qpy rx)) den)
            lr (sqrt (+ (* rx rx) (* ry ry))) ls (sqrt (+ (* sx sx) (* sy sy))))
      (if (and (> tt (/ ard:th-pt lr)) (< tt (- 1.0 (/ ard:th-pt lr)))
               (> uu (/ ard:th-pt ls)) (< uu (- 1.0 (/ ard:th-pt ls))))
        (list (+ (car a) (* tt rx)) (+ (cadr a) (* tt ry)) (ard:z a))
        nil))))
(defun ard:add-node (p nodes / hit n)
  (foreach n nodes (if (ard:pt-eq p n) (setq hit T)))
  (if hit nodes (cons p nodes)))
(defun ard:dir-label (dx dy / a)
  (if (< (sqrt (+ (* dx dx) (* dy dy))) ard:th-pt)
    "OTHER"
    (progn
      (setq a (atan dy dx))
      (cond ((< (abs a) ard:th-ang) "E")
            ((or (< (abs (- a pi)) ard:th-ang) (< (abs (+ a pi)) ard:th-ang)) "W")
            ((< (abs (- a (/ pi 2.0))) ard:th-ang) "N")
            ((< (abs (+ a (/ pi 2.0))) ard:th-ang) "S")
            (T "OTHER")))))
;;; arm: (label angle far-point handle profile width)
(defun ard:mk-arm (n far s / dx dy)
  (setq dx (- (car far) (car n)) dy (- (cadr far) (cadr n)))
  (list (ard:dir-label dx dy) (atan dy dx) far (nth 2 s) (nth 3 s) (nth 4 s)))
(defun ard:arms-at (n segs / arms s a b)
  (foreach s segs
    (setq a (car s) b (cadr s))
    (cond
      ((ard:pt-eq n a) (setq arms (cons (ard:mk-arm n b s) arms)))
      ((ard:pt-eq n b) (setq arms (cons (ard:mk-arm n a s) arms)))
      ((< (car (ard:seg-nearest n a b)) ard:th-pt)
       (setq arms (cons (ard:mk-arm n a s) (cons (ard:mk-arm n b s) arms))))))
  (reverse arms))
(defun ard:same-angle (a b)
  (and (< (abs (sin (- a b))) ard:th-ang) (> (cos (- a b)) 0.0)))
(defun ard:dedupe-arms (arms / out a hit o)
  (foreach a arms
    (setq hit nil)
    (foreach o out (if (ard:same-angle (cadr a) (cadr o)) (setq hit T)))
    (if (not hit) (setq out (cons a out))))
  (reverse out))
(defun ard:dir-sort (labels / out l)
  (foreach l '("E" "W" "N" "S" "OTHER")
    (if (member l labels) (setq out (cons l out))))
  (reverse out))
(defun ard:sort-arms (arms / out l a)
  (foreach l '("E" "W" "N" "S" "OTHER")
    (foreach a arms (if (= (car a) l) (setq out (cons a out)))))
  (reverse out))
(defun ard:classify (dirs / has-ew has-ns)
  (setq has-ew (and (member "E" dirs) (member "W" dirs))
        has-ns (and (member "N" dirs) (member "S" dirs)))
  (cond
    ((member "OTHER" dirs) "UNKNOWN")
    ((= (length dirs) 1) "END")
    ((= (length dirs) 2) (if (or has-ew has-ns) "STRAIGHT" "ELBOW"))
    ((= (length dirs) 3) (if (or has-ew has-ns) "TEE" "UNKNOWN"))
    ((= (length dirs) 4) "CROSS")
    (T "UNKNOWN")))
(defun ard:unique-nums (nums / out x hit o)
  (foreach x nums
    (setq hit nil)
    (foreach o out (if (< (abs (- o x)) ard:th-pt) (setq hit T)))
    (if (not hit) (setq out (cons x out))))
  (reverse out))
;;; internal junction alist
(defun ard:junction-at (n segs lay / arms uarms overlap dirs a class)
  (setq arms (ard:arms-at n segs) uarms (ard:sort-arms (ard:dedupe-arms arms)))
  (setq overlap (/= (length arms) (length uarms)))
  (setq dirs (ard:dir-sort (mapcar 'car uarms)))
  (setq class (if overlap "UNKNOWN" (ard:classify dirs)))
  (list (cons "layout" lay) (cons "pt" n) (cons "arms" uarms) (cons "arm_count" (length arms))
        (cons "dirs" dirs) (cons "degree" (length uarms)) (cons "class" class)
        (cons "overlap" overlap)
        (cons "profiles" (ard:unique-strs (mapcar '(lambda (x) (nth 4 x)) uarms)))
        (cons "widths" (ard:unique-nums (mapcar '(lambda (x) (nth 5 x)) uarms)))))
(defun ard:jget (k j) (cdr (assoc k j)))
(defun ard:build-topology (paths / lays lay segs nodes s o q p n)
  (setq ard:*segs* nil ard:*junctions* nil)
  (setq lays (ard:unique-strs (mapcar '(lambda (x) (ard:get "layout" x)) paths)))
  (foreach lay lays
    (setq segs nil nodes nil)
    (foreach p paths
      (if (= (ard:get "layout" p) lay) (setq segs (append segs (ard:path-segs p)))))
    (foreach s segs
      (setq nodes (ard:add-node (car s) nodes))
      (setq nodes (ard:add-node (cadr s) nodes)))
    (foreach s segs
      (foreach o segs
        (if (and (not (eq s o)) (setq q (ard:seg-cross s o)))
          (setq nodes (ard:add-node q nodes)))))
    (setq ard:*segs* (append ard:*segs* segs))
    (foreach n (reverse nodes)
      (setq ard:*junctions* (append ard:*junctions* (list (ard:junction-at n segs lay)))))))

;;; ====================================================================
;;; 7. connection geometry per arm
;;; ====================================================================
(defun ard:arm-frame (arm / a)
  (setq a (cadr arm))
  (list (list (cos a) (sin a)) (list (- (sin a)) (cos a))))
;;; pts: (x y [tag]).  pick 'MIN = nearest to J ahead along the arm, 'MAX = farthest.
;;; -> (best cmin cmax face-count handles) or nil
(defun ard:face (pts jp u n halfw pick / rx ry ax cr best sel p fmn fmx hs cnt crs)
  (foreach p pts
    (setq rx (- (car p) (car jp)) ry (- (cadr p) (cadr jp)))
    (setq ax (+ (* rx (car u)) (* ry (cadr u))) cr (+ (* rx (car n)) (* ry (cadr n))))
    (if (and (<= (abs cr) halfw) (or (eq pick 'MAX) (> ax (- ard:th-pt))))
      (progn
        (setq sel (cons (list ax cr (if (cddr p) (caddr p) nil)) sel))
        (if (or (null best) (if (eq pick 'MAX) (> ax best) (< ax best)))
          (setq best ax)))))
  (if sel
    (progn
      (foreach p sel
        (if (<= (abs (- (car p) best)) ard:th-face)
          (progn
            (setq cnt (1+ (if cnt cnt 0)))
            (setq crs (cons (cadr p) crs))
            (if (or (null fmn) (< (cadr p) fmn)) (setq fmn (cadr p)))
            (if (or (null fmx) (> (cadr p) fmx)) (setq fmx (cadr p)))
            (if (and (caddr p) (not (member (caddr p) hs))) (setq hs (cons (caddr p) hs))))))
      (list best fmn fmx cnt (reverse hs) crs))
    nil))
(defun ard:world-pt (jp u n ax cr)
  (list (+ (car jp) (* (car u) ax) (* (car n) cr))
        (+ (cadr jp) (* (cadr u) ax) (* (cadr n) cr))
        (ard:z jp)))
(defun ard:straight-pts (layout / out st v)
  (foreach st ard:*straights*
    (if (= (ard:get "layout" st) layout)
      (foreach v (ard:get "_verts" st)
        (setq out (cons (list (car v) (cadr v) (ard:get "handle" st)) out)))))
  out)
(defun ard:mid (f) (/ (+ (cadr f) (caddr f)) 2.0))
(defun ard:w2b (fit p / ip rot sc base rx ry)
  ;; world point -> block coordinates (inverse of the INSERT transform, block base included)
  (setq ip (ard:get "_ip" fit) rot (ard:get "_rot" fit) sc (ard:get "_scale" fit)
        base (ard:get "_base" fit) rx (- (car p) (car ip)) ry (- (cadr p) (cadr ip)))
  (list (+ (car base) (/ (+ (* rx (cos rot)) (* ry (sin rot))) (car sc)))
        (+ (cadr base) (/ (- (* ry (cos rot)) (* rx (sin rot))) (cadr sc)))))
(defun ard:wvec2b (fit v / rot sc)
  ;; world vector -> block-space vector (rotation and scale only)
  (setq rot (ard:get "_rot" fit) sc (ard:get "_scale" fit))
  (list (/ (+ (* (car v) (cos rot)) (* (cadr v) (sin rot))) (car sc))
        (/ (- (* (cadr v) (cos rot)) (* (car v) (sin rot))) (cadr sc))))
(defun ard:pt2 (p) (if p (ard:arr (list (float (car p)) (float (cadr p)))) nil))
;;; ---- opening (block -> WCS) and arm matching -------------------------------
(defun ard:lin (m v)
  (list (+ (* (nth 0 m) (car v)) (* (nth 2 m) (cadr v))) (+ (* (nth 1 m) (car v)) (* (nth 3 m) (cadr v)))))
(defun ard:opening-wcs (op m / k)
  (setq k (ard:vlen (ard:lin m (cdr (assoc "u" op)))))
  (list (cons "id" (cdr (assoc "id" op)))
        (cons "center" (ard:mat-apply m (cdr (assoc "center" op))))
        (cons "normal" (ard:vunit (ard:lin m (cdr (assoc "normal" op)))))
        (cons "rails" (mapcar '(lambda (r) (mapcar '(lambda (q) (ard:mat-apply m q)) r)) (cdr (assoc "rails" op))))
        (cons "w_cc" (* k (cdr (assoc "width_center_to_center" op))))
        (cons "w_out" (* k (cdr (assoc "width_outer" op))))
        (cons "w_in" (* k (cdr (assoc "width_inner" op))))
        (cons "amb" (cdr (assoc "ambiguous" op)))))
(defun ard:amb-facing (arm opws / u hit o)
  (setq u (list (cos (cadr arm)) (sin (cadr arm))))
  (foreach o opws
    (if (and (cdr (assoc "amb" o)) (> (ard:vdot (cdr (assoc "normal" o)) u) (cos (* ard:th-open-dir-deg (/ pi 180.0)))))
      (setq hit T)))
  hit)
(defun ard:next-node-dist (jp u n lay / best j rx ry ax cr)
  ;; distance from the junction to the nearest OTHER PATH node straight ahead along this arm
  (foreach j ard:*junctions*
    (if (= (ard:jget "layout" j) lay)
      (progn
        (setq rx (- (car (ard:jget "pt" j)) (car jp)) ry (- (cadr (ard:jget "pt" j)) (cadr jp))
              ax (+ (* rx (car u)) (* ry (cadr u))) cr (+ (* rx (car n)) (* ry (cadr n))))
        (if (and (> ax ard:th-pt) (< (abs cr) ard:th-pt) (or (null best) (< ax best))) (setq best ax)))))
  best)
(defun ard:match-opening (arm jp opws used / u best bd o d)
  (setq u (list (cos (cadr arm)) (sin (cadr arm))))
  (foreach o opws
    (if (and (not (member (cdr (assoc "id" o)) used)) (not (cdr (assoc "amb" o)))
             (> (ard:vdot (cdr (assoc "normal" o)) u) (cos (* ard:th-open-dir-deg (/ pi 180.0)))))
      (progn
        (setq d (ard:d2 (cdr (assoc "center" o)) jp))
        (if (or (null bd) (< d bd)) (setq best o bd d)))))
  best)
(defun ard:drop (lst n) (while (and lst (> n 0)) (setq lst (cdr lst) n (1- n))) lst)
(defun ard:rail-stat (l) (list (apply 'min l) (apply 'max l) (/ (+ (apply 'min l) (apply 'max l)) 2.0)))
(defun ard:split-rails (crs / s gap i best g1)
  ;; cluster the cross coordinates of a Straight end face into two rails at the largest gap
  (setq s (vl-sort crs '<))
  (if (< (length s) 2)
    nil
    (progn
      (setq best -1.0 i 0 g1 0)
      (while (< (1+ i) (length s))
        (setq gap (- (nth (1+ i) s) (nth i s)))
        (if (> gap best) (setq best gap g1 i))
        (setq i (1+ i)))
      (list (ard:rail-stat (ard:take s (1+ g1))) (ard:rail-stat (ard:drop s (1+ g1)))))))
(defun ard:opening-json (opw jp u n / rails)
  (ard:obj
    (list (cons "id" (cdr (assoc "id" opw)))
          (cons "center" (ard:pt3 (list (car (cdr (assoc "center" opw))) (cadr (cdr (assoc "center" opw))) (ard:z jp))))
          (cons "outward_normal" (ard:pt2 (cdr (assoc "normal" opw))))
          (cons "width_center_to_center_mm" (cdr (assoc "w_cc" opw)))
          (cons "width_outer_mm" (cdr (assoc "w_out" opw)))
          (cons "width_inner_mm" (cdr (assoc "w_in" opw)))
          (cons "rails"
            (ard:arr
              (mapcar '(lambda (r)
                (ard:obj (list (cons "outer_edge" (ard:pt2 (nth 0 r))) (cons "inner_edge" (ard:pt2 (nth 1 r)))
                               (cons "rail_center" (ard:pt2 (nth 2 r)))
                               (cons "outer_edge_lateral_mm" (ard:vdot (ard:vsub (nth 0 r) jp) n))
                               (cons "inner_edge_lateral_mm" (ard:vdot (ard:vsub (nth 1 r) jp) n))
                               (cons "center_lateral_mm" (ard:vdot (ard:vsub (nth 2 r) jp) n)))))
                (vl-sort (cdr (assoc "rails" opw))
                         '(lambda (a b) (< (ard:vdot (ard:vsub (nth 2 a) jp) n) (ard:vdot (ard:vsub (nth 2 b) jp) n))))))))))
;;; opening = fitting side (derived from block geometry), Straight = the generated Straight end face
;;; on the same arm.  expected = opening centre, actual = Straight connection point.
(defun ard:connection (fit jn arm spts op derived / jp fr u n w halfw fpts sf ff status err ex ac reason d nextd
                                                    fax flat method rails srails k)
  (setq jp (ard:jget "pt" jn) fr (ard:arm-frame arm) u (car fr) n (cadr fr)
        w (nth 5 arm) halfw (+ (/ w 2.0) ard:th-corridor))
  (setq fpts (ard:get "_pts" fit))
  (setq nextd (ard:next-node-dist jp u n (ard:get "layout" fit)))
  (setq sf (ard:face (if nextd
                       (vl-remove-if-not '(lambda (q) (<= (+ (* (- (car q) (car jp)) (car u)) (* (- (cadr q) (cadr jp)) (cadr u)))
                                                          (+ nextd ard:th-pt)))
                                         spts)
                       spts)
                     jp u n halfw 'MIN))
  (cond
    ((null sf)
     (setq status "NOT_COMPUTABLE"
           reason (if nextd
                    (strcat "no generated Straight between this junction and the next PATH node " (rtos nextd 2 3)
                            " mm ahead (segment too short for a Straight, or Straight missing)")
                    "no generated Straight vertex ahead of the junction on this arm (Straight missing or outside the corridor)")))
    (op
     (setq method "derived_opening"
           fax (ard:vdot (ard:vsub (cdr (assoc "center" op)) jp) u)
           flat (ard:vdot (ard:vsub (cdr (assoc "center" op)) jp) n)))
    ((eq derived 'AMB)
     (setq status "AMBIGUOUS_OPENING"
           reason "the block has several stacked openings on the face that looks at this arm; the real one cannot be identified from geometry"))
    (derived
     (setq status "NO_OPENING"
           reason "the fitting has no opening facing this arm direction (rotation / fitting type does not match the PATH junction)"))
    (T
     (setq ff (if fpts (ard:face fpts jp u n 1.0e12 'MAX) nil) method "extreme_face_fallback")
     (if ff
       (setq fax (car ff) flat (ard:mid ff))
       (setq status "NOT_COMPUTABLE" reason "fitting block definition has no readable geometry"))))
  (if (and sf (null status))
    (progn
      (setq ex (ard:world-pt jp u n fax flat)
            ac (ard:world-pt jp u n (car sf) (ard:mid sf))
            err (ard:d2 ex ac) d (list (- (car ex) (car ac)) (- (cadr ex) (cadr ac)))
            status (cond ((<= err ard:th-exact) "EXACT") ((<= err ard:th-near) "NEAR") (T "MISMATCH")))
      (if op
        (progn
          (setq rails (cdr (ard:get "rails" (ard:opening-json op jp u n))))
          (setq srails (ard:split-rails (nth 5 sf)))))))
  (ard:obj
    (list (cons "direction" (car arm)) (cons "angle_deg" (* (cadr arm) (/ 180.0 pi)))
          (cons "path_handle" (nth 3 arm)) (cons "arm_profile" (nth 4 arm)) (cons "arm_width" w)
          (cons "status" status) (cons "reason" reason) (cons "method" method)
          (cons "opening_id" (if op (cdr (assoc "id" op)) nil))
          (cons "next_node_distance_mm" nextd)
          (cons "expected_source" (if op "centre of the fitting opening derived from block geometry (rail centres midpoint), transformed to WCS"
                                      "centre of farthest end face of fitting geometry (fallback, weak evidence)"))
          (cons "actual_source" "centre of the nearest generated Straight end face on this arm")
          (cons "expected" (if ex (ard:pt3 ex) nil))
          (cons "actual" (if ac (ard:pt3 ac) nil))
          (cons "delta_x" (if d (- (car d)) nil))
          (cons "delta_y" (if d (- (cadr d)) nil))
          (cons "delta_convention" "delta = actual (Straight) - expected (opening); axial/lateral errors are fitting minus Straight")
          (cons "error_mm" err)
          (cons "axial_error_mm" (if (and ex sf) (- fax (car sf)) nil))
          (cons "lateral_error_mm" (if (and ex sf) (- flat (ard:mid sf)) nil))
          (cons "opening_distance_from_junction_mm" (if ex fax nil))
          (cons "straight_start_distance_from_junction_mm" (if sf (car sf) nil))
          (cons "straight_end_width_mm" (if sf (- (caddr sf) (cadr sf)) nil))
          (cons "fitting_opening_width_mm" (if op (cdr (assoc "w_out" op)) nil))
          (cons "opening" (if op (ard:opening-json op jp u n) nil))
          (cons "straight_rails"
            (if srails
              (ard:arr (mapcar '(lambda (r) (ard:obj (list (cons "min_lateral_mm" (nth 0 r)) (cons "max_lateral_mm" (nth 1 r))
                                                           (cons "center_lateral_mm" (nth 2 r))))) srails))
              nil))
          (cons "rail_center_differences_mm"
            (if (and rails srails (= (length rails) (length srails)))
              (ard:arr (mapcar '(lambda (fr sr) (- (ard:get "center_lateral_mm" fr) (nth 2 sr))) rails srails))
              nil))
          (cons "expected_in_block_coords" (if ex (ard:pt2 (ard:w2b fit ex)) nil))
          (cons "actual_in_block_coords" (if ac (ard:pt2 (ard:w2b fit ac)) nil))
          (cons "delta_in_block_coords" (if d (ard:pt2 (ard:wvec2b fit (list (- (car d)) (- (cadr d))))) nil))
          (cons "straight_handles" (if sf (ard:arr (nth 4 sf)) nil))
          (cons "_err" err) (cons "_status" status) (cons "_d" d) (cons "_u" u) (cons "_n" n)
          (cons "_wratio" (if (and op sf (> (- (caddr sf) (cadr sf)) 1.0e-9))
                            (/ (cdr (assoc "w_out" op)) (- (caddr sf) (cadr sf))) nil)))))
;;; raw evidence: how far the fitting geometry extends from the junction along E,W,N,S
(defun ard:geometry-extents (fit jn / jp fpts out lab u n ext)
  (setq jp (ard:jget "pt" jn) fpts (ard:get "_pts" fit))
  (foreach lab '("E" "W" "N" "S")
    (setq u (cond ((= lab "E") '(1.0 0.0)) ((= lab "W") '(-1.0 0.0))
                  ((= lab "N") '(0.0 1.0)) (T '(0.0 -1.0))))
    (setq n (list (- (cadr u)) (car u)))
    (setq ext (if fpts (ard:face fpts jp u n 1.0e12 'MAX) nil))
    (setq out (cons (cons lab (if ext (car ext) nil)) out)))
  (reverse out))
;;; Decompose the per-arm deltas  d_i = a_i*u_i + l_i*n_i  into one rigid world translation T of the
;;; whole fitting (solved from the LATERAL components, least squares over arms) plus a per-arm axial
;;; residual.  T != 0 with small residuals -> placement offset (origin / BASE_OFFSET);
;;; T ~ 0 with equal axial residuals -> arm length / TAKEOFF; large lateral residual -> rotation / wrong type.
(defun ard:translation-fit (fit conns jdelta / cs c sxx sxy syy bx by det tx ty n u l a per rms cnt hints tb ax-res mag ac)
  (foreach c conns (if (ard:get "_d" c) (setq cs (cons c cs))))
  (setq cs (reverse cs))
  (if (< (length cs) 2)
    nil
    (progn
      (setq sxx 0.0 sxy 0.0 syy 0.0 bx 0.0 by 0.0)
      (foreach c cs
        (setq n (ard:get "_n" c) l (ard:get "lateral_error_mm" c))
        (setq sxx (+ sxx (* (car n) (car n))) sxy (+ sxy (* (car n) (cadr n))) syy (+ syy (* (cadr n) (cadr n)))
              bx (+ bx (* (car n) l)) by (+ by (* (cadr n) l))))
      (setq det (- (* sxx syy) (* sxy sxy)))
      (if (< (abs det) 1.0e-9)
        nil
        (progn
          (setq tx (/ (- (* syy bx) (* sxy by)) det) ty (/ (- (* sxx by) (* sxy bx)) det))
          (setq rms 0.0 cnt 0)
          (foreach c cs
            (setq n (ard:get "_n" c) u (ard:get "_u" c) l (ard:get "lateral_error_mm" c) a (ard:get "axial_error_mm" c))
            (setq per (cons
              (ard:obj (list (cons "direction" (ard:get "direction" c))
                             (cons "axial_residual_mm" (- a (+ (* tx (car u)) (* ty (cadr u)))))
                             (cons "lateral_residual_mm" (- l (+ (* tx (car n)) (* ty (cadr n)))))))
              per))
            (setq rms (+ rms (expt (ard:get "lateral_residual_mm" (car per)) 2)) cnt (1+ cnt)))
          (setq rms (sqrt (/ rms cnt)) per (reverse per) mag (sqrt (+ (* tx tx) (* ty ty))))
          (setq tb (ard:wvec2b fit (list tx ty)))
          (if (> mag ard:th-near)
            (setq hints (cons (strcat "PLACEMENT_OFFSET: fitting is rigidly displaced by " (rtos mag 2 4)
                                      " mm (block-space vector " (rtos (car tb) 2 4) ", " (rtos (cadr tb) 2 4)
                                      "): block origin / BASE_OFFSET / insertion point") hints)))
          (if (and jdelta (< (ard:d2 (list (- (car jdelta)) (- (cadr jdelta))) tb) 0.01))
            (setq hints (cons (strcat "TRANSLATION_EQUALS_JOINT_DELTA: the shift equals (derived block joint - junction position in block coords) = ("
                                      (rtos (- (car jdelta)) 2 4) ", " (rtos (- (cadr jdelta)) 2 4)
                                      "); derived from block geometry alone, independent of the Straights") hints)))
          (foreach ac (cdr (ard:get "block_arc_centres" fit))
            (if (and (< (abs (- (car tb) (ard:get "x" ac))) 0.01) (< (abs (- (cadr tb) (ard:get "y" ac))) 0.01))
              (setq hints (cons (strcat "TRANSLATION_EQUALS_BLOCK_ARC_CENTRE: block-space shift equals the arc centre ("
                                        (rtos (ard:get "x" ac) 2 4) ", " (rtos (ard:get "y" ac) 2 4)
                                        "), i.e. the Router assumed the arc pivot sits at the block origin") hints))))
          (foreach c per
            (if (> (abs (ard:get "axial_residual_mm" c)) ard:th-near)
              (setq hints (cons (strcat "ARM_LENGTH_OR_TAKEOFF: arm " (ard:get "direction" c)
                                        " axial residual " (rtos (ard:get "axial_residual_mm" c) 2 4)
                                        " mm (positive = fitting extends past the Straight start)") hints))))
          (if (> rms ard:th-near)
            (setq hints (cons (strcat "LATERAL_RESIDUAL: rms " (rtos rms 2 4)
                                      " mm after removing the translation: rotation mapping / wrong fitting type / PATH direction") hints)))
          (ard:obj
            (list (cons "arms_used" (length cs))
                  (cons "dx" tx) (cons "dy" ty) (cons "magnitude_mm" mag)
                  (cons "in_block_coords" (ard:pt2 tb))
                  (cons "rms_lateral_residual_mm" rms)
                  (cons "per_arm" (ard:arr per))
                  (cons "hints" (ard:arr (reverse hints)))
                  (cons "meaning" "T solved from lateral components of the per-arm deltas (least squares); axial_residual = axial error minus T projected on the arm; in_block_coords = T un-rotated and un-scaled"))))))))

;;; ====================================================================
;;; 8. fitting analysis
;;; ====================================================================
(defun ard:issue (sev code detail)
  (ard:obj (list (cons "severity" sev) (cons "code" code) (cons "detail" detail))))
(defun ard:has-sev (issues sev / hit i)
  (foreach i issues (if (= (ard:get "severity" i) sev) (setq hit T)))
  hit)
(defun ard:rank-junctions (refpt lay / out j)
  (foreach j ard:*junctions*
    (if (and (= (ard:jget "layout" j) lay) (>= (ard:jget "degree" j) 2))
      (setq out (cons (cons (ard:d2 refpt (ard:jget "pt" j)) j) out))))
  (vl-sort out '(lambda (a b) (< (car a) (car b)))))
(defun ard:take (lst n / out i)
  (setq i 0)
  (while (and lst (< i n)) (setq out (cons (car lst) out) lst (cdr lst) i (1+ i)))
  (reverse out))
(defun ard:prox (d)
  (cond ((null d) "unrelated") ((<= d ard:th-exact) "exact") ((<= d ard:th-near) "near") (T "unrelated")))
(defun ard:path-candidates (fit jn / ip out p best bestpt mv mi s r i jd lay v)
  (setq ip (ard:get "_ip" fit) lay (ard:get "layout" fit))
  (foreach p ard:*paths*
    (if (= (ard:get "layout" p) lay)
      (progn
        (setq best nil bestpt nil mv nil mi nil jd nil)
        (foreach s (ard:path-segs p)
          (setq r (ard:seg-nearest ip (car s) (cadr s)))
          (if (or (null best) (< (car r) best)) (setq best (car r) bestpt (cadr r)))
          (if jn
            (progn
              (setq r (ard:seg-nearest (ard:jget "pt" jn) (car s) (cadr s)))
              (if (or (null jd) (< (car r) jd)) (setq jd (car r))))))
        (setq i 0)
        (foreach v (ard:get "_verts" p)
          (if (or (null mv) (< (ard:d2 ip v) mv)) (setq mv (ard:d2 ip v) mi i))
          (setq i (1+ i)))
        (setq out
          (cons
            (ard:obj
              (list (cons "handle" (ard:get "handle" p)) (cons "entity_type" (ard:get "entity_type" p))
                    (cons "profile" (ard:get "profile" p)) (cons "width" (ard:get "width" p))
                    (cons "min_distance" best) (cons "nearest_point" (ard:pt3 bestpt))
                    (cons "min_vertex_distance" mv) (cons "nearest_vertex_index" mi)
                    (cons "junction_distance" jd)
                    (cons "touches_junction" (ard:bool (and jd (<= jd ard:th-exact))))
                    (cons "relation" (ard:prox (if jn jd best)))
                    (cons "_rank" (cond (jd jd) (best best) (T 1.0e99)))))
            out)))))
  (vl-sort out '(lambda (a b) (< (ard:get "_rank" a) (ard:get "_rank" b)))))
(defun ard:profile-issues (fit jn / fp profs issues p)
  (setq fp (ard:get "profile" fit) profs (ard:jget "profiles" jn))
  (foreach p profs
    (if (/= (strcase p) (strcase fp))
      (setq issues
        (cons (if (ard:get "resolved_profile_prefix" fit)
                (ard:issue "FAIL" "FITTING_PROFILE_MISMATCH"
                  (strcat "fitting block profile " fp " vs PATH profile " p))
                (ard:issue "WARN" "FITTING_UNPREFIXED_PATH_PROFILE"
                  (strcat "fitting block has no profile prefix (DEFAULT) but PATH profile is " p)))
              issues))))
  (if (> (length profs) 1)
    (setq issues (cons (ard:issue "FAIL" "PATH_PROFILE_MISMATCH"
                         (strcat "PATHs at this junction use different profiles: " (ard:join profs ", ")))
                       issues)))
  (if (> (length (ard:jget "widths" jn)) 1)
    (setq issues (cons (ard:issue "WARN" "PATH_WIDTH_MISMATCH"
                         (strcat "PATHs at this junction have different widths: "
                                 (ard:join (mapcar '(lambda (w) (rtos w 2 3)) (ard:jget "widths" jn)) ", ")))
                       issues)))
  (reverse issues))
(defun ard:conn-issues (conns / issues c e)
  (foreach c conns
    (setq e (ard:get "_err" c))
    (cond
      ((= (ard:get "_status" c) "MISMATCH")
       (setq issues (cons (ard:issue "FAIL" "CONNECTION_MISMATCH"
         (strcat "arm " (ard:get "direction" c) ": error " (rtos e 2 4)
                 " mm (axial " (ard:t (ard:get "axial_error_mm" c) 4)
                 ", lateral " (ard:t (ard:get "lateral_error_mm" c) 4) ")")) issues)))
      ((= (ard:get "_status" c) "NEAR")
       (setq issues (cons (ard:issue "WARN" "CONNECTION_NEAR"
         (strcat "arm " (ard:get "direction" c) ": error " (rtos e 2 4) " mm")) issues)))
      ((= (ard:get "_status" c) "AMBIGUOUS_OPENING")
       (setq issues (cons (ard:issue "WARN" "OPENING_AMBIGUOUS"
         (strcat "arm " (ard:get "direction" c) ": " (ard:get "reason" c))) issues)))
      ((= (ard:get "_status" c) "NO_OPENING")
       (setq issues (cons (ard:issue "FAIL" "ARM_WITHOUT_OPENING"
         (strcat "arm " (ard:get "direction" c) ": " (ard:get "reason" c))) issues)))
      ((= (ard:get "_status" c) "NOT_COMPUTABLE")
       (setq issues (cons (ard:issue "WARN" "CONNECTION_NOT_COMPUTABLE"
         (strcat "arm " (ard:get "direction" c) ": " (ard:get "reason" c))) issues))))
    (if (and (ard:get "_wratio" c) (or (< (ard:get "_wratio" c) 0.5) (> (ard:get "_wratio" c) 1.5)))
      (setq issues (cons (ard:issue "WARN" "OPENING_WIDTH_MISMATCH"
        (strcat "arm " (ard:get "direction" c) ": fitting end face is "
                (rtos (ard:get "fitting_opening_width_mm" c) 2 3) " mm wide vs Straight end "
                (rtos (ard:get "straight_end_width_mm" c) 2 3)
                " mm (fitting may have no opening in this direction)")) issues))))
  (reverse issues))
(defun ard:junction-obj (jn / )
  (ard:obj
    (list (cons "junction_x" (car (ard:jget "pt" jn))) (cons "junction_y" (cadr (ard:jget "pt" jn)))
          (cons "junction_z" (ard:z (ard:jget "pt" jn)))
          (cons "layout" (ard:jget "layout" jn))
          (cons "degree" (ard:jget "degree" jn))
          (cons "directions" (ard:arr (ard:jget "dirs" jn)))
          (cons "classification" (ard:jget "class" jn))
          (cons "arm_count" (ard:jget "arm_count" jn))
          (cons "overlapping_arms" (ard:bool (ard:jget "overlap" jn)))
          (cons "profiles" (ard:arr (ard:jget "profiles" jn)))
          (cons "widths" (ard:arr (ard:jget "widths" jn)))
          (cons "arms"
            (ard:arr
              (mapcar '(lambda (a)
                (ard:obj (list (cons "direction" (car a)) (cons "angle_deg" (* (cadr a) (/ 180.0 pi)))
                               (cons "far_point" (ard:pt3 (caddr a))) (cons "path_handle" (nth 3 a))
                               (cons "profile" (nth 4 a)) (cons "width" (nth 5 a)))))
                (ard:jget "arms" jn)))))))
(defun ard:z-normal-p (e)
  (and e (< (abs (car e)) 1.0e-9) (< (abs (cadr e)) 1.0e-9) (> (caddr e) 0.0)))
(defun ard:analyze-fitting (fit / ip bb ref refsrc rank best second jn cand spts conns issues
                                 status maxerr c e ang k g blk rel local ops opws op used unp jb m stacked)
  (setq ip (ard:get "_ip" fit))
  (setq bb (ard:bbox-of (ard:get "_pts" fit)))
  (setq ref (if bb
              (list (/ (+ (car (car bb)) (car (cadr bb))) 2.0) (/ (+ (cadr (car bb)) (cadr (cadr bb))) 2.0))
              ip)
        refsrc (if bb "fitting block-definition geometry bbox centre" "insertion point"))
  (setq rank (ard:rank-junctions ref (ard:get "layout" fit)))
  (setq best (car rank) second (cadr rank) jn (if best (cdr best) nil))
  (setq blk (ard:block-local (ard:get "raw_block_name" fit)))
  (if (not (car blk))
    (setq issues (cons (ard:issue "FAIL" "BLOCK_DEFINITION_MISSING"
                         (strcat "block " (ard:get "raw_block_name" fit) " is not defined in this drawing"))
                       issues)))
  (if (not (ard:z-normal-p (ard:get "_ext" fit)))
    (setq issues (cons (ard:issue "WARN" "INSERT_EXTRUSION_NOT_Z"
                         "INSERT extrusion is not +Z: analysis is done in the XY plane and mirrored/rotated blocks may be misjudged")
                       issues)))
  (setq cand (ard:path-candidates fit jn))
  (if (null jn)
    (setq issues (cons (ard:issue "WARN" "NO_JUNCTION" "no PATH junction (degree >= 2) found in this layout") issues))
    (progn
      (setq spts (ard:straight-pts (ard:get "layout" fit)))
      (setq ops (nth 6 blk) m (ard:get "_matrix" fit))
      (setq opws (mapcar '(lambda (o) (ard:opening-wcs o m)) ops))
      (foreach g (ard:jget "arms" jn)
        (setq op (ard:match-opening g (ard:jget "pt" jn) opws used))
        (if op (setq used (cons (cdr (assoc "id" op)) used)))
        (setq conns (cons (ard:connection fit jn g spts op
                                          (cond ((null ops) nil) ((and (null op) (ard:amb-facing g opws)) 'AMB) (T T)))
                          conns)))
      (if (and (null ops) (car blk) (cadr blk))
        (setq issues (cons (ard:issue "WARN" "OPENING_NOT_DERIVED"
                             "no opening could be derived from the block geometry; the weak extreme-face fallback was used") issues)))
      (setq conns (reverse conns))
      (setq stacked (vl-some '(lambda (o) (cdr (assoc "amb" o))) opws))   ; block with stacked variants: its other openings are not trustworthy either
      (foreach o opws
        (if (and (not (member (cdr (assoc "id" o)) used)) (not (cdr (assoc "amb" o))))
          (setq issues (cons (ard:issue (if stacked "WARN" "FAIL") (if stacked "OPENING_UNPAIRED_IN_STACKED_BLOCK" "OPENING_WITHOUT_ARM")
            (strcat "fitting opening " (cdr (assoc "id" o)) " at (" (rtos (car (cdr (assoc "center" o))) 2 3) ", "
                    (rtos (cadr (cdr (assoc "center" o))) 2 3) ") faces "
                    (ard:dir-label (car (cdr (assoc "normal" o))) (cadr (cdr (assoc "normal" o))))
                    " but the PATH junction has no arm in that direction")) issues))))
      (setq issues (append (reverse (ard:conn-issues conns)) issues))
      (if (/= (ard:get "fitting_type" fit) (ard:jget "class" jn))
        (setq issues (cons (ard:issue "FAIL" "FITTING_TOPOLOGY_MISMATCH"
                             (strcat "fitting is " (ard:get "fitting_type" fit) " but PATH junction is "
                                     (ard:jget "class" jn) " (" (ard:join (ard:jget "dirs" jn) ",") ")"))
                           issues)))
      (setq issues (append (reverse (ard:profile-issues fit jn)) issues))
      (foreach c conns
        (setq e (ard:get "_err" c))
        (if (and e (or (null maxerr) (> e maxerr))) (setq maxerr e)))))
  (setq issues (reverse issues))
  (setq status
    (cond ((null jn) "NOT_COMPUTABLE")
          ((ard:has-sev issues "FAIL") "FAIL")
          ((ard:has-sev issues "WARN") "WARN")
          (T "OK")))
  (if jn
    (setq local (ard:w2b fit (ard:jget "pt" jn))
          rel (list (- (car (ard:jget "pt" jn)) (car ip)) (- (cadr (ard:jget "pt" jn)) (cadr ip)))))
  (setq ang (ard:get "rotation_deg" fit))
  (setq k (fix (+ (/ ang 90.0) (if (>= ang 0.0) 0.5 -0.5))))
  (ard:obj (append (cdr fit)
    (list
      (cons "junction_reference_point" (ard:pt3 ref))
      (cons "junction_reference_source" refsrc)
      (cons "junction" (if jn (ard:junction-obj jn) nil))
      (cons "junction_distance_to_reference" (if best (car best) nil))
      (cons "second_nearest_junction_distance" (if second (car second) nil))
      (cons "junction_offset_from_insert" (if jn (ard:pt2 rel) nil))
      (cons "junction_in_block_coords" (if jn (ard:pt2 local) nil))
      (cons "rotation_nearest_quarter_turn_deg" (* 90.0 k))
      (cons "rotation_residual_deg" (- ang (* 90.0 k)))
      (cons "scale_is_uniform"
        (ard:bool (< (abs (- (abs (car (ard:get "_scale" fit))) (abs (cadr (ard:get "_scale" fit))))) 1.0e-9)))
      (cons "fitting_geometry_extent_from_junction_mm"
        (if jn (ard:obj (mapcar '(lambda (g) (cons (car g) (cdr g))) (ard:geometry-extents fit jn))) nil))
      (cons "opening_method" (if (nth 6 blk) "derived_opening" "extreme_face_fallback"))
      (cons "openings"
        (ard:arr (mapcar '(lambda (o)
                   (ard:obj (list (cons "id" (cdr (assoc "id" o)))
                                  (cons "center" (ard:pt2 (cdr (assoc "center" o))))
                                  (cons "outward_normal" (ard:pt2 (cdr (assoc "normal" o))))
                                  (cons "facing" (ard:dir-label (car (cdr (assoc "normal" o))) (cadr (cdr (assoc "normal" o)))))
                                  (cons "width_center_to_center_mm" (cdr (assoc "w_cc" o)))
                                  (cons "width_outer_mm" (cdr (assoc "w_out" o))))))
                 opws)))
      (cons "derived_joint_block" (if (nth 7 blk) (ard:pt2 (car (nth 7 blk))) nil))
      (cons "derived_joint_rms" (if (nth 7 blk) (cadr (nth 7 blk)) nil))
      (cons "derived_joint_wcs" (if (nth 7 blk) (ard:pt2 (ard:mat-apply (ard:get "_matrix" fit) (car (nth 7 blk)))) nil))
      (cons "junction_minus_derived_joint_block"
        (if (and jn (nth 7 blk)) (ard:pt2 (ard:vsub local (car (nth 7 blk)))) nil))
      (cons "connections" (ard:arr conns))
      (cons "translation_fit" (if jn (ard:translation-fit fit conns (if (nth 7 blk) (ard:vsub local (car (nth 7 blk))) nil)) nil))
      (cons "max_connection_error_mm" maxerr)
      (cons "connected_path_candidates" (ard:arr (ard:take cand ard:th-cand-max)))
      (cons "issues" (ard:arr issues))
      (cons "status" status)
      (cons "_jpt" (if jn (ard:jget "pt" jn) nil))
      (cons "_jlayout" (ard:get "layout" fit))))))

;;; ====================================================================
;;; 9. junction records (CTRDIAGALL)
;;; ====================================================================
(defun ard:junction-record (jn afits / hs mx issues st f e cls)
  (foreach f afits
    (if (and (ard:get "_jpt" f) (= (ard:get "_jlayout" f) (ard:jget "layout" jn))
             (ard:pt-eq (ard:get "_jpt" f) (ard:jget "pt" jn)))
      (progn
        (setq hs (cons f hs))
        (setq e (ard:get "max_connection_error_mm" f))
        (if (and e (or (null mx) (> e mx))) (setq mx e)))))
  (setq hs (reverse hs) cls (ard:jget "class" jn))
  (if (and (null hs) (member cls '("ELBOW" "TEE" "CROSS")))
    (setq issues (cons (ard:issue "WARN" "NO_FITTING_AT_JUNCTION"
                         (strcat "PATH junction is " cls " but no fitting is attached")) issues)))
  (if (> (length hs) 1)
    (setq issues (cons (ard:issue "WARN" "MULTIPLE_FITTINGS_AT_JUNCTION"
                         (strcat (itoa (length hs)) " fittings resolve to this junction")) issues)))
  (if (> (length (ard:jget "profiles" jn)) 1)
    (setq issues (cons (ard:issue "FAIL" "PATH_PROFILE_MISMATCH"
                         (strcat "profiles: " (ard:join (ard:jget "profiles" jn) ", "))) issues)))
  (if (> (length (ard:jget "widths" jn)) 1)
    (setq issues (cons (ard:issue "WARN" "PATH_WIDTH_MISMATCH" "different widths at junction") issues)))
  (if (or (= cls "UNKNOWN") (ard:jget "overlap" jn))
    (setq issues (cons (ard:issue "WARN" "UNSUPPORTED_TOPOLOGY"
                         "non-orthogonal or overlapping arms (Router cannot place a fitting)") issues)))
  (foreach f hs
    (if (= (ard:get "status" f) "FAIL")
      (setq issues (cons (ard:issue "FAIL" "FITTING_FAILED"
                           (strcat "fitting " (ard:get "handle" f) " has status FAIL")) issues))))
  (setq issues (reverse issues))
  (setq st (cond ((ard:has-sev issues "FAIL") "FAIL") ((ard:has-sev issues "WARN") "WARN") (T "OK")))
  (append (cdr (ard:junction-obj jn))
    (list (cons "fitting_handles" (ard:arr (mapcar '(lambda (f) (ard:get "handle" f)) hs)))
          (cons "fitting_count" (length hs))
          (cons "max_connection_error_mm" mx)
          (cons "issues" (ard:arr issues))
          (cons "status" st))))

;;; ====================================================================
;;; 10. report
;;; ====================================================================
(defun ard:stamp-of (s / p d f)
  ;; CDATE text such as "20260930.12" -> "20260930_120000" (rtos drops trailing zeros)
  (setq p (vl-string-search "." s))
  (setq d (if p (substr s 1 p) s) f (if p (substr s (+ p 2)) ""))
  (while (< (strlen f) 6) (setq f (strcat f "0")))
  (strcat d "_" (substr f 1 6)))
(defun ard:stamp () (ard:stamp-of (rtos (getvar "CDATE") 2 6)))
(defun ard:sysvar (name / r)
  (setq r (vl-catch-all-apply 'getvar (list name)))
  (if (vl-catch-all-error-p r) nil r))
(defun ard:count-by (items key / out cell v)
  (foreach v items
    (setq cell (assoc (ard:get key v) out))
    (if cell
      (setq out (subst (cons (car cell) (1+ (cdr cell))) cell out))
      (setq out (cons (cons (if (ard:get key v) (ard:get key v) "UNKNOWN") 1) out))))
  (ard:obj (reverse out)))
(defun ard:thresholds ()
  (ard:obj
    (list (cons "coordinate_tolerance_mm" ard:th-pt)
          (cons "orthogonal_angle_tolerance_rad" ard:th-ang)
          (cons "connection_exact_mm" ard:th-exact)
          (cons "connection_near_mm" ard:th-near)
          (cons "arm_corridor_extra_mm" ard:th-corridor)
          (cons "end_face_band_mm" ard:th-face)
          (cons "arc_sampling_step_deg" ard:th-arc-deg)
          (cons "path_candidates_listed" ard:th-cand-max)
          (cons "opening_geometry_tolerance_relative_to_block_diagonal" ard:th-geom-rel)
          (cons "opening_direction_tolerance_deg" ard:th-open-dir-deg)
          (cons "connection_status_rule" "error <= exact_mm -> EXACT; <= near_mm -> NEAR; else MISMATCH; expected or actual missing -> NOT_COMPUTABLE")
          (cons "relation_rule" "path relation from distance to the selected junction (else to the insertion point): <= exact_mm exact; <= near_mm near; else unrelated")
          (cons "expected_point_definition" "centre of the fitting OPENING derived from block geometry (cap pair + rail edges), transformed by scale/rotation/insertion to WCS")
          (cons "actual_point_definition" "centre of the nearest generated Straight end face along the arm (Straight vertices in the arm corridor)")
          (cons "units_note" "all *_mm values are drawing units; the Router assumes millimetres (see insunits)"))))
(defun ard:dedupe-arcs (recs / out r hit o)
  (foreach r recs
    (setq hit nil)
    (foreach o out
      (if (and (< (ard:d2 (car r) (car o)) 0.001) (< (abs (- (cadr r) (cadr o))) 0.001)
               (< (abs (- (caddr r) (caddr o))) 1.0e-6) (< (abs (- (cadddr r) (cadddr o))) 1.0e-6))
        (setq hit T)))
    (if (not hit) (setq out (cons r out))))
  (reverse out))
(defun ard:opening-local-json (o)
  (ard:obj
    (list (cons "id" (cdr (assoc "id" o)))
          (cons "opening_center" (ard:pt2 (cdr (assoc "center" o))))
          (cons "outward_normal" (ard:pt2 (cdr (assoc "normal" o))))
          (cons "width_rail_center_to_rail_center" (cdr (assoc "width_center_to_center" o)))
          (cons "width_outer_edge_to_outer_edge" (cdr (assoc "width_outer" o)))
          (cons "width_inner_edge_to_inner_edge" (cdr (assoc "width_inner" o)))
          (cons "rail_end_cap_length" (cdr (assoc "cap_length" o)))
          (cons "ambiguous" (ard:bool (cdr (assoc "ambiguous" o))))
          (cons "rails"
            (ard:arr (mapcar '(lambda (r)
              (ard:obj (list (cons "outer_edge_point" (ard:pt2 (nth 0 r)))
                             (cons "inner_edge_point" (ard:pt2 (nth 1 r)))
                             (cons "rail_center_point" (ard:pt2 (nth 2 r))))))
              (cdr (assoc "rails" o))))))))
(defun ard:block-report (name / bl base pts)
  (setq bl (ard:block-local name) pts (cadr bl) base (ard:block-base name))
  (ard:obj
    (list (cons "name" name) (cons "found" (ard:bool (car bl)))
          (cons "block_origin" (ard:pt2 base))
          (cons "bbox_local" (ard:bb-json (ard:bbox-of pts)))
          (cons "entity_tally" (ard:obj (mapcar '(lambda (c) (cons (car c) (cdr c))) (reverse (caddr bl)))))
          (cons "geometry_tolerance_block_units" (ard:geom-tol pts))
          (cons "segments"
            (ard:arr (mapcar '(lambda (sg)
              (ard:obj (list (cons "p" (ard:pt2 (car sg))) (cons "q" (ard:pt2 (cadr sg)))
                             (cons "length" (ard:d2 (car sg) (cadr sg))))))
              (nth 4 bl))))
          (cons "arcs"
            (ard:arr (mapcar '(lambda (a)
              (ard:obj (list (cons "center" (ard:pt2 (car a))) (cons "radius" (cadr a))
                             (cons "start_angle_deg" (* (caddr a) (/ 180.0 pi)))
                             (cons "end_angle_deg" (* (cadddr a) (/ 180.0 pi))))))
              (ard:dedupe-arcs (nth 5 bl)))))
          (cons "openings" (ard:arr (mapcar 'ard:opening-local-json (nth 6 bl))))
          (cons "derived_joint" (if (nth 7 bl) (ard:pt2 (car (nth 7 bl))) nil))
          (cons "derived_joint_axis_rms" (if (nth 7 bl) (cadr (nth 7 bl)) nil))
          (cons "definitions"
            (ard:obj (list (cons "outer_edge" "extreme end point of a rail end cap (outside of the rail)")
                           (cons "inner_edge" "other end point of the cap (rail side facing the tray interior)")
                           (cons "rail_center" "midpoint of the cap = centre line of that rail")
                           (cons "opening_center" "midpoint of the two rail centres")
                           (cons "block_origin" "block base point (INSERT block-space origin)")))))))
(defun ard:build-report (mode fits sel-paths sel-straights / dwg)
  (setq dwg (ard:sysvar "DWGNAME"))
  (ard:obj
    (list (cons "schema_version" ard:schema-version)
          (cons "tool" "autocad_router_diagnostics")
          (cons "tool_version" ard:version)
          (cons "mode" mode)
          (cons "timestamp" (ard:stamp))
          (cons "drawing" dwg)
          (cons "drawing_path" (strcat (vl-princ-to-string (ard:sysvar "DWGPREFIX")) (vl-princ-to-string dwg)))
          (cons "acad_version" (ard:sysvar "ACADVER"))
          (cons "insunits" (ard:sysvar "INSUNITS"))
          (cons "read_only" T)
          (cons "run_note" ard:run-note)
          (cons "thresholds" (ard:thresholds))
          (cons "counts"
            (ard:obj (list (cons "fittings" (length fits))
                           (cons "fitting_types" (ard:count-by fits "fitting_type"))
                           (cons "paths_in_drawing" (length ard:*paths*))
                           (cons "paths_in_report" (length sel-paths))
                           (cons "straights_in_drawing" (length ard:*straights*))
                           (cons "straights_in_report" (length sel-straights))
                           (cons "junctions_analyzed" (length ard:*junctions*)))))
          (cons "fittings" (ard:arr fits))
          (cons "blocks" (ard:arr (mapcar 'ard:block-report
                                          (ard:unique-strs (mapcar '(lambda (f) (ard:get "raw_block_name" f)) fits)))))
          (cons "junctions"
            (ard:arr
              (if (= mode "export") nil
                (mapcar '(lambda (jn) (ard:obj (ard:junction-record jn fits)))
                  (vl-remove-if-not
                    '(lambda (jn)
                       (and (>= (ard:jget "degree" jn) 2)
                            (or (= mode "all")
                                (vl-some '(lambda (f)
                                            (and (ard:get "_jpt" f) (ard:pt-eq (ard:get "_jpt" f) (ard:jget "pt" jn))))
                                         fits))))
                    ard:*junctions*)))))
          (cons "paths" (ard:arr sel-paths))
          (cons "generated_geometry" (ard:arr sel-straights))
          (cons "warnings" (ard:arr (reverse ard:*warnings*))))))

;;; ---- selection of PATHs / Straights for single-fitting reports --------
(defun ard:by-handle (lst h / hit x)
  (foreach x lst (if (= (ard:get "handle" x) h) (setq hit x)))
  hit)
(defun ard:single-selection (afit / hs sh out c cn)
  (foreach c (cdr (ard:get "connected_path_candidates" afit))
    (setq hs (cons (ard:get "handle" c) hs)))
  (foreach cn (cdr (ard:get "connections" afit))
    (foreach c (cdr (ard:get "straight_handles" cn)) (if (not (member c sh)) (setq sh (cons c sh)))))
  (list (vl-remove-if 'null (mapcar '(lambda (h) (ard:by-handle ard:*paths* h)) (reverse hs)))
        (vl-remove-if 'null (mapcar '(lambda (h) (ard:by-handle ard:*straights* h)) (reverse sh)))))

;;; ====================================================================
;;; 11. file output (external files only)
;;; ====================================================================
(defun ard:mkdirs (d / parent)
  (if (and d (> (strlen d) 0))
    (progn
      (if (member (substr d (strlen d) 1) (list "/" ard:bs)) (setq d (substr d 1 (1- (strlen d)))))
      (if (not (vl-file-directory-p d))
        (progn
          (setq parent (vl-filename-directory d))
          (if (and parent (> (strlen parent) 0) (/= parent d)) (ard:mkdirs parent))
          (vl-mkdir d))))))
(defun ard:out-base (mode / d base n)
  (setq d ard:out-dir)
  (ard:mkdirs d)
  (if (not (vl-file-directory-p (if (member (substr d (strlen d) 1) (list "/" ard:bs)) (substr d 1 (1- (strlen d))) d)))
    (setq d (strcat (getenv "TEMP") "/")))
  (setq base (strcat d "ctrdiag_" (ard:stamp) (cond ((= mode "all") "_all") ((= mode "export") "_export") (T ""))))
  (setq n 1)
  (while (findfile (strcat base (if (> n 1) (strcat "_" (itoa n)) "") ".json")) (setq n (1+ n)))
  (strcat base (if (> n 1) (strcat "_" (itoa n)) "")))
(defun ard:open-out (path / f)
  (setq f (open path "w" "utf8"))
  (if f (setq ard:*files* (cons f ard:*files*)))
  f)
(defun ard:close-out (f)
  (if f (progn (close f) (setq ard:*files* (vl-remove f ard:*files*)))))
(defun ard:close-all ()
  (foreach f ard:*files* (vl-catch-all-apply 'close (list f)))
  (setq ard:*files* nil))
(setq ard:csv-cols
  '("drawing" "handle" "object_type" "block_name" "fitting_type" "profile" "width" "x" "y" "z"
    "scale_x" "scale_y" "rotation_deg" "junction_x" "junction_y" "degree" "classification"
    "max_connection_error_mm" "status" "layout" "directions" "issues"))
(defun ard:issue-codes (obj / out i)
  (foreach i (cdr (ard:get "issues" obj)) (setq out (cons (ard:get "code" i) out)))
  (ard:join (reverse out) ";"))
(defun ard:csv-fitting-row (drw f / j)
  (setq j (ard:get "junction" f))
  (list drw (ard:get "handle" f) "FITTING" (ard:get "raw_block_name" f) (ard:get "fitting_type" f)
        (ard:get "profile" f) (if j (car (cdr (ard:get "widths" j))) nil)
        (ard:get "insert_x" f) (ard:get "insert_y" f) (ard:get "insert_z" f)
        (ard:get "scale_x" f) (ard:get "scale_y" f) (ard:get "rotation_deg" f)
        (if j (ard:get "junction_x" j) nil) (if j (ard:get "junction_y" j) nil)
        (if j (ard:get "degree" j) nil) (if j (ard:get "classification" j) nil)
        (ard:get "max_connection_error_mm" f) (if (ard:get "status" f) (ard:get "status" f) "DATA")
        (ard:get "layout" f) (if j (ard:join (cdr (ard:get "directions" j)) ";") nil)
        (ard:issue-codes f)))
(defun ard:csv-junction-row (drw j)
  (list drw (ard:join (cdr (ard:get "fitting_handles" j)) ";") "JUNCTION" nil nil
        (ard:join (cdr (ard:get "profiles" j)) ";") (car (cdr (ard:get "widths" j)))
        (ard:get "junction_x" j) (ard:get "junction_y" j) (ard:get "junction_z" j)
        nil nil nil (ard:get "junction_x" j) (ard:get "junction_y" j)
        (ard:get "degree" j) (ard:get "classification" j)
        (ard:get "max_connection_error_mm" j) (ard:get "status" j)
        (ard:get "layout" j) (ard:join (cdr (ard:get "directions" j)) ";") (ard:issue-codes j)))
(defun ard:csv-path-row (drw p / v1)
  (setq v1 (car (cdr (ard:get "vertices" p))))
  (list drw (ard:get "handle" p) "PATH" nil nil (ard:get "profile" p) (ard:get "width" p)
        (if v1 (ard:get "x" v1) nil) (if v1 (ard:get "y" v1) nil) (if v1 (ard:get "z" v1) nil)
        nil nil nil nil nil nil nil nil
        (if (ard:tp (ard:get "profile_explicit" p)) "OK" "WARN")
        (ard:get "layout" p) nil (if (ard:tp (ard:get "profile_explicit" p)) "" "PROFILE_IMPLICIT_DEFAULT")))
(defun ard:write-csv (report path / f drw x)
  (setq f (ard:open-out path) drw (ard:get "drawing" report))
  (if f
    (progn
      (princ (strcat (ard:csv-row ard:csv-cols) ard:lf) f)
      (foreach x (cdr (ard:get "fittings" report))
        (princ (strcat (ard:csv-row (ard:csv-fitting-row drw x)) ard:lf) f))
      (foreach x (cdr (ard:get "junctions" report))
        (princ (strcat (ard:csv-row (ard:csv-junction-row drw x)) ard:lf) f))
      (foreach x (cdr (ard:get "paths" report))
        (princ (strcat (ard:csv-row (ard:csv-path-row drw x)) ard:lf) f))
      (ard:close-out f)
      path)
    nil))
(defun ard:write-json (report path / f)
  (setq f (ard:open-out path))
  (if f
    (progn (ard:jw report f 0) (princ ard:lf f) (ard:close-out f) path)
    nil))

(princ)

;;; ====================================================================
;;; 12. human-readable text (console summary + TXT report)
;;; ====================================================================
(defun ard:ps (p) (if p (strcat "(" (ard:t (car p) 4) ", " (ard:t (cadr p) 4) ")") "n/a"))
(defun ard:arr-pt (a) (if a (cdr a) nil))
(defun ard:fitting-lines (f / j lines c p i)
  (setq j (ard:get "junction" f))
  (setq lines
    (list
      (strcat "FITTING " (ard:get "handle" f) "  type=" (if (ard:get "fitting_type" f) (ard:get "fitting_type" f) "?")
              "  block=" (ard:get "raw_block_name" f) "  status=" (if (ard:get "status" f) (ard:get "status" f) "DATA"))
      (strcat "  insert " (ard:ps (list (ard:get "insert_x" f) (ard:get "insert_y" f)))
              " z=" (ard:t (ard:get "insert_z" f) 4)
              "  rotation " (ard:t (ard:get "rotation_deg" f) 4) " deg"
              "  scale (" (ard:t (ard:get "scale_x" f) 6) ", " (ard:t (ard:get "scale_y" f) 6) ", "
              (ard:t (ard:get "scale_z" f) 6) ")  layer " (ard:get "layer" f))
      (strcat "  profile " (ard:get "profile" f) "  prefix "
              (if (ard:get "resolved_profile_prefix" f) (ard:get "resolved_profile_prefix" f) "(none)")
              "  type source " (ard:get "fitting_type_source" f))
      (strcat "  bbox " (ard:ps (ard:arr-pt (ard:get "bounding_box_min" f))) " .. "
              (ard:ps (ard:arr-pt (ard:get "bounding_box_max" f))) " (" (ard:get "bounding_box_source" f) ")")))
  (if j
    (progn
      (setq lines
        (append lines
          (list
            (strcat "  junction " (ard:ps (list (ard:get "junction_x" j) (ard:get "junction_y" j)))
                    "  degree " (itoa (ard:get "degree" j))
                    "  directions " (ard:join (cdr (ard:get "directions" j)) ",")
                    "  classification " (ard:get "classification" j))
            (strcat "  junction offset from insert " (ard:ps (ard:arr-pt (ard:get "junction_offset_from_insert" f)))
                    "  junction in block coords " (ard:ps (ard:arr-pt (ard:get "junction_in_block_coords" f))))
            (strcat "  derived block joint (from opening axes) " (ard:ps (ard:arr-pt (ard:get "derived_joint_block" f)))
                    "  junction minus derived joint (block coords) " (ard:ps (ard:arr-pt (ard:get "junction_minus_derived_joint_block" f)))
                    "  opening method " (ard:get "opening_method" f))
            (strcat "  rotation nearest quarter turn " (ard:t (ard:get "rotation_nearest_quarter_turn_deg" f) 1)
                    " deg, residual " (ard:t (ard:get "rotation_residual_deg" f) 6)))))
      (foreach c (cdr (ard:get "connections" f))
        (setq lines
          (append lines
            (list
              (strcat "  arm " (ard:get "direction" c) " opening " (if (ard:get "opening_id" c) (ard:get "opening_id" c) "-") " path " (ard:get "path_handle" c)
                      " (" (ard:get "arm_profile" c) " / " (ard:t (ard:get "arm_width" c) 1) ") [" (ard:get "status" c) "]"
                      (if (ard:get "expected" c)
                        (strcat "  opening " (ard:ps (ard:arr-pt (ard:get "expected" c)))
                                " Straight " (ard:ps (ard:arr-pt (ard:get "actual" c)))
                                " delta (" (ard:t (ard:get "delta_x" c) 5) ", " (ard:t (ard:get "delta_y" c) 5) ")"
                                " error " (ard:t (ard:get "error_mm" c) 5) " mm"
                                " (axial " (ard:t (ard:get "axial_error_mm" c) 5) ", lateral " (ard:t (ard:get "lateral_error_mm" c) 5) ")")
                        (strcat "  " (if (ard:get "reason" c) (ard:get "reason" c) "")))))
            (if (ard:get "expected" c)
              (list (strcat "      in block coords: opening " (ard:ps (ard:arr-pt (ard:get "expected_in_block_coords" c)))
                            " Straight " (ard:ps (ard:arr-pt (ard:get "actual_in_block_coords" c)))
                            " delta " (ard:ps (ard:arr-pt (ard:get "delta_in_block_coords" c)))
                            "  opening width " (ard:t (ard:get "fitting_opening_width_mm" c) 3)
                            " vs Straight end " (ard:t (ard:get "straight_end_width_mm" c) 3)))
              nil))))
      (if (ard:get "translation_fit" f)
        (progn
          (setq lines
            (append lines
              (list (strcat "  translation fit: world (" (ard:t (ard:get "dx" (ard:get "translation_fit" f)) 4) ", "
                            (ard:t (ard:get "dy" (ard:get "translation_fit" f)) 4) ") |"
                            (ard:t (ard:get "magnitude_mm" (ard:get "translation_fit" f)) 4)
                            "| mm, in block coords " (ard:ps (ard:arr-pt (ard:get "in_block_coords" (ard:get "translation_fit" f))))
                            ", rms lateral residual " (ard:t (ard:get "rms_lateral_residual_mm" (ard:get "translation_fit" f)) 4) " mm"))))
          (foreach c (cdr (ard:get "per_arm" (ard:get "translation_fit" f)))
            (setq lines
              (append lines
                (list (strcat "    arm " (ard:get "direction" c) " residual after translation: axial "
                              (ard:t (ard:get "axial_residual_mm" c) 4) " mm, lateral "
                              (ard:t (ard:get "lateral_residual_mm" c) 4) " mm")))))
          (foreach c (cdr (ard:get "hints" (ard:get "translation_fit" f)))
            (setq lines (append lines (list (strcat "    hint: " c))))))))
    ) ; end (if j
  (foreach c (cdr (ard:get "block_arc_centres" f))
    (setq lines
      (append lines
        (list (strcat "  block arc centre " (ard:ps (list (ard:get "x" c) (ard:get "y" c)))
                      " radii " (ard:join (mapcar '(lambda (r) (ard:t r 3)) (cdr (ard:get "radii" c))) ","))))))
  (foreach c (cdr (ard:get "connected_path_candidates" f))
    (setq lines
      (append lines
        (list (strcat "  candidate PATH " (ard:get "handle" c) "  " (ard:get "relation" c)
                      "  min_distance " (ard:t (ard:get "min_distance" c) 4)
                      "  junction_distance " (ard:t (ard:get "junction_distance" c) 4)
                      "  profile " (ard:get "profile" c) "  width " (ard:t (ard:get "width" c) 1))))))
  (foreach c (cdr (ard:get "issues" f))
    (setq lines
      (append lines
        (list (strcat "  [" (ard:get "severity" c) "] " (ard:get "code" c) ": " (ard:get "detail" c))))))
  lines)
(defun ard:write-txt (report path / f x l)
  (setq f (ard:open-out path))
  (if f
    (progn
      (princ (strcat "Router diagnostic report  mode=" (ard:get "mode" report) "  tool " (ard:get "tool_version" report) ard:lf) f)
      (princ (strcat "Drawing: " (ard:get "drawing_path" report) ard:lf) f)
      (princ (strcat "Timestamp: " (ard:get "timestamp" report) "  (read-only; no drawing changes)" ard:lf) f)
      (princ (strcat "Fittings: " (itoa (length (cdr (ard:get "fittings" report))))
                     "  PATHs in report: " (itoa (length (cdr (ard:get "paths" report))))
                     "  Straights in report: " (itoa (length (cdr (ard:get "generated_geometry" report))))
                     "  Junctions: " (itoa (length (cdr (ard:get "junctions" report)))) ard:lf ard:lf) f)
      (foreach x (cdr (ard:get "fittings" report))
        (foreach l (ard:fitting-lines x) (princ (strcat l ard:lf) f))
        (princ ard:lf f))
      (foreach x (cdr (ard:get "junctions" report))
        (if (/= (ard:get "status" x) "OK")
          (progn
            (princ (strcat "JUNCTION " (ard:ps (list (ard:get "junction_x" x) (ard:get "junction_y" x)))
                           " " (ard:get "classification" x) " status=" (ard:get "status" x)
                           " fittings=" (ard:join (cdr (ard:get "fitting_handles" x)) ",") ard:lf) f)
            (foreach l (cdr (ard:get "issues" x))
              (princ (strcat "  [" (ard:get "severity" l) "] " (ard:get "code" l) ": " (ard:get "detail" l) ard:lf) f)))))
      (foreach x (cdr (ard:get "paths" report))
        (princ (strcat "PATH " (ard:get "handle" x) " " (ard:get "entity_type" x)
                       " profile=" (ard:get "profile" x) (if (ard:tp (ard:get "profile_explicit" x)) "" "(implicit)")
                       " width=" (ard:t (ard:get "width" x) 1) (if (ard:tp (ard:get "width_explicit" x)) "" "(implicit)")
                       " vertices=" (itoa (ard:get "vertex_count" x)) ard:lf) f)
        (foreach l (cdr (ard:get "vertices" x))
          (princ (strcat "    [" (itoa (ard:get "index" l)) "] " (ard:ps (list (ard:get "x" l) (ard:get "y" l)))
                         " z=" (ard:t (ard:get "z" l) 4) ard:lf) f)))
      (foreach x (cdr (ard:get "warnings" report))
        (princ (strcat "WARNING " (ard:get "code" x) ": " (ard:get "message" x) ard:lf) f))
      (ard:close-out f)
      path)
    nil))

;;; ====================================================================
;;; 13. orchestration
;;; ====================================================================
(defun ard:reset ()
  (setq ard:*bcache* nil ard:*warnings* nil ard:*paths* nil ard:*straights* nil
        ard:*junctions* nil ard:*segs* nil))
(defun ard:run (mode sel / fits afits report base sel2 jf cf tf x l)
  (ard:reset)
  (setq ard:*paths* (ard:scan-paths) ard:*straights* (ard:scan-straights))
  (setq fits (if sel (list (ard:make-fitting sel)) (ard:scan-fittings)))
  (cond
    ((= mode "export")
     (setq report (ard:build-report mode fits ard:*paths* ard:*straights*)))
    (T
     (ard:build-topology ard:*paths*)
     (setq afits (mapcar 'ard:analyze-fitting fits))
     (if sel
       (progn
         (setq sel2 (ard:single-selection (car afits)))
         (setq report (ard:build-report mode afits (car sel2) (cadr sel2))))
       (setq report (ard:build-report mode afits ard:*paths* ard:*straights*)))))
  (setq base (ard:out-base mode))
  (setq jf (ard:write-json report (strcat base ".json"))
        cf (ard:write-csv report (strcat base ".csv"))
        tf (ard:write-txt report (strcat base ".txt")))
  (princ (strcat ard:lf "CTRDIAG (" mode "): " (itoa (length fits)) " fitting(s), "
                 (itoa (length ard:*paths*)) " PATH(s), " (itoa (length ard:*straights*)) " Straight(s). Drawing NOT modified."))
  (if (= mode "single")
    (foreach l (ard:fitting-lines (car (cdr (ard:get "fittings" report))))
      (princ (strcat ard:lf l))))
  (if (= mode "all")
    (foreach x (cdr (ard:get "fittings" report))
      (princ (strcat ard:lf "  " (ard:get "handle" x) " " (ard:get "fitting_type" x) " "
                     (ard:get "status" x) " max_err=" (ard:t (ard:get "max_connection_error_mm" x) 4)))))
  (princ (strcat ard:lf "JSON: " (if jf jf "(write failed)") ard:lf "CSV : " (if cf cf "(write failed)")
                 ard:lf "TXT : " (if tf tf "(write failed)")))
  (setq ard:*last-report* report)
  jf)
(defun ard:guarded (mode sel label / r)
  (setq r (vl-catch-all-apply 'ard:run (list mode sel)))
  (if (vl-catch-all-error-p r)
    (progn
      (ard:close-all)
      (princ (strcat ard:lf label " stopped (diagnosis only; drawing NOT modified): "
                     (vl-catch-all-error-message r)))
      nil)
    r))

;;; ====================================================================
;;; 14. commands  (nothing runs at load time)
;;; ====================================================================
(defun c:CTRDIAG ( / *error* pick en ed)
  (defun *error* (msg)
    (ard:close-all)
    (if (and msg (not (wcmatch (strcase msg) "*BREAK*,*CANCEL*,*QUIT*,*EXIT*")))
      (princ (strcat ard:lf "CTRDIAG stopped (drawing NOT modified): " msg)))
    (princ))
  (setq pick (entsel (strcat ard:lf "CTRDIAG - select a Router fitting INSERT: ")))
  (cond
    ((null pick) (princ (strcat ard:lf "CTRDIAG: nothing selected.")))
    (T
     (setq en (car pick) ed (entget en))
     (cond
       ((/= (cdr (assoc 0 ed)) "INSERT")
        (princ (strcat ard:lf "CTRDIAG: the selected object is a " (cdr (assoc 0 ed)) ", not a block INSERT.")))
       ((null (ard:fitting-kind ed en))
        (princ (strcat ard:lf "CTRDIAG: block " (cdr (assoc 2 ed)) " does not match a Router fitting pattern.")))
       (T (ard:guarded "single" en "CTRDIAG")))))
  (princ))
(defun c:CTRDIAGALL ( / *error*)
  (defun *error* (msg)
    (ard:close-all)
    (if (and msg (not (wcmatch (strcase msg) "*BREAK*,*CANCEL*,*QUIT*,*EXIT*")))
      (princ (strcat ard:lf "CTRDIAGALL stopped (drawing NOT modified): " msg)))
    (princ))
  (ard:guarded "all" nil "CTRDIAGALL")
  (princ))
(defun c:CTRDIAGEXPORT ( / *error*)
  (defun *error* (msg)
    (ard:close-all)
    (if (and msg (not (wcmatch (strcase msg) "*BREAK*,*CANCEL*,*QUIT*,*EXIT*")))
      (princ (strcat ard:lf "CTRDIAGEXPORT stopped (drawing NOT modified): " msg)))
    (princ))
  (ard:guarded "export" nil "CTRDIAGEXPORT")
  (princ))

(princ (strcat ard:lf "Router Diagnostics " ard:version " loaded (read-only): CTRDIAG, CTRDIAGALL, CTRDIAGEXPORT"))
(princ)
