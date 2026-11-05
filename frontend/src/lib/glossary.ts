/**
 * Glosario de terminos fiscales japoneses (確定申告) con su explicacion breve
 * en castellano. Es la base de la "capa de ayuda ES": la UI permanece en
 * japones (documento oficial para 国税庁 / Hacienda japonesa), pero cuando la
 * ayuda ES esta activa, estos terminos muestran una glosa que ensena que
 * significan.
 *
 * Cada entrada: lectura (furigana romanizada opcional) + glosa corta (1-2
 * frases) en castellano, con tono que ensena. Codigo en ingles, contenido ES.
 */

/** Una entrada del glosario fiscal JP -> ES. */
export interface GlossaryEntry {
  /** Termino tal cual aparece en la UI (japones). */
  readonly term: string;
  /** Lectura romanizada (ayuda a pronunciar / buscar). */
  readonly reading: string;
  /** Traduccion/etiqueta corta en castellano (para subtitulos). */
  readonly es: string;
  /** Explicacion breve en castellano (1-2 frases, tono que ensena). */
  readonly help: string;
}

/**
 * Diccionario de terminos, indexado por el termino japones exacto. Usar
 * `lookupTerm()` para resolver con tolerancia (ignora sufijos como 額/金 y
 * variantes con barra "/").
 */
export const GLOSSARY: Readonly<Record<string, GlossaryEntry>> = {
  確定申告: {
    term: "確定申告",
    reading: "kakutei shinkoku",
    es: "Declaración de la renta",
    help: "La declaración anual de impuestos ante Hacienda japonesa. Se reportan los ingresos del año y se calcula el impuesto a pagar o a devolver.",
  },
  年度: {
    term: "年度",
    reading: "nendo",
    es: "Año fiscal (ejercicio)",
    help: "El ejercicio fiscal de un año (ej. 2025 = 令和7年分). Cada año se declara por separado: la app guarda los datos de cada 年度 aparte y podés cambiar de año desde el selector del encabezado.",
  },
  青色申告: {
    term: "青色申告",
    reading: "aoiro shinkoku",
    es: "Declaración azul",
    help: "Régimen de declaración para autónomos que llevan contabilidad por partida doble. Da más beneficios fiscales (hasta 650.000 yenes de deducción especial) a cambio de llevar libros formales.",
  },
  過去の申告: {
    term: "過去の申告",
    reading: "kako no shinkoku",
    es: "Declaraciones anteriores",
    help: "El archivo histórico de tus 確定申告 de años anteriores. Subís el PDF de cada año y la app guarda un registro consultable y compara la evolución año a año.",
  },
  電子帳簿保存法: {
    term: "電子帳簿保存法",
    reading: "denshi chōbo hozon hō",
    es: "Ley de conservación electrónica de libros",
    help: "Ley japonesa que regula cómo conservar libros y comprobantes en formato electrónico. Exige guardar los documentos de forma íntegra e indexada durante al menos 7 años.",
  },
  税務署: {
    term: "税務署",
    reading: "zeimusho",
    es: "Oficina de Hacienda",
    help: "La oficina tributaria local ante la que se presenta el 確定申告. Cada zona tiene la suya (ej. 津島税務署).",
  },
  更正の請求: {
    term: "更正の請求",
    reading: "kousei no seikyuu",
    es: "Solicitud de corrección (a tu favor)",
    help: "Cuando ya declaraste y pagaste de más (o te devolvieron de menos), le PEDÍS a Hacienda que corrija a tu favor. No es volver a declarar: esperás que el 税務署 lo apruebe. Plazo: 5 años. No genera recargo (加算税).",
  },
  修正申告: {
    term: "修正申告",
    reading: "shuusei shinkoku",
    es: "Declaración rectificativa (a favor del fisco)",
    help: "Lo contrario al 更正の請求: corregís porque pagaste de MENOS. Puede llevar un recargo (加算税). No es el caso cuando recuperás deducciones que perdiste.",
  },
  更正通知書: {
    term: "更正通知書",
    reading: "kousei tsuuchisho",
    es: "Notificación de corrección",
    help: "El documento con el que Hacienda confirma que aprobó tu 更正の請求. Después de recibirlo, te pagan la devolución (還付), normalmente en unos 2-3 meses.",
  },
  加算税: {
    term: "加算税",
    reading: "kasanzei",
    es: "Recargo por declaración incorrecta",
    help: "Sanción que se suma cuando declaraste de menos y corregís tarde. El 更正の請求 (corrección a TU favor) NO genera 加算税: es seguro.",
  },
  住宅借入金等特別控除: {
    term: "住宅借入金等特別控除",
    reading: "juutaku kariirekin-tou tokubetsu koujo",
    es: "Deducción por préstamo de vivienda (住宅ローン控除)",
    help: "Deducción sobre la CUOTA (税額控除) por el préstamo de tu vivienda: resta directo del impuesto, 1 a 1. El primer año hay que adjuntar varios documentos; si faltan, Hacienda la rechaza (se puede recuperar con un 更正の請求).",
  },
  住宅ローン控除: {
    term: "住宅ローン控除",
    reading: "juutaku roon koujo",
    es: "Deducción por préstamo de vivienda",
    help: "Nombre coloquial del 住宅借入金等特別控除. Deducción sobre la cuota por el préstamo de tu casa: cada yen deducido es un yen menos de impuesto.",
  },
  白色申告: {
    term: "白色申告",
    reading: "shiroiro shinkoku",
    es: "Declaración blanca",
    help: "Régimen simplificado, sin la deducción especial de la azul. Requiere menos contabilidad pero ofrece menos ventajas fiscales.",
  },
  控除: {
    term: "控除",
    reading: "koujo",
    es: "Deducción",
    help: "Una cantidad que se resta antes de calcular el impuesto. Cuantas más deducciones válidas, menos impuesto pagas.",
  },
  所得控除: {
    term: "所得控除",
    reading: "shotoku koujo",
    es: "Deducción sobre la renta",
    help: "Deducciones que se restan del ingreso ANTES de calcular el impuesto (seguros, gastos médicos, familia, etc.). Reducen la base imponible.",
  },
  税額控除: {
    term: "税額控除",
    reading: "zeigaku koujo",
    es: "Deducción sobre la cuota",
    help: "Deducciones que se restan directamente del impuesto YA calculado (p.ej. préstamo de vivienda). Valen 1 a 1: 10.000 yenes de deducción = 10.000 menos de impuesto.",
  },
  基礎控除: {
    term: "基礎控除",
    reading: "kiso koujo",
    es: "Deducción básica",
    help: "Deducción automática que tiene casi todo el mundo (hasta 480.000 yenes). No hace falta registrarla: se aplica sola.",
  },
  社会保険料控除: {
    term: "社会保険料控除",
    reading: "shakai hokenryou koujo",
    es: "Deducción de seguros sociales",
    help: "El total pagado de seguro de salud nacional y pensión nacional se deduce íntegro, sin tope. Casi todos los autónomos la usan.",
  },
  医療費控除: {
    term: "医療費控除",
    reading: "iryouhi koujo",
    es: "Deducción de gastos médicos",
    help: "Si los gastos médicos del año (menos lo que cubrió el seguro) superan 100.000 yenes, el exceso es deducible. Se pueden sumar los de la familia.",
  },
  生命保険料控除: {
    term: "生命保険料控除",
    reading: "seimei hokenryou koujo",
    es: "Deducción de seguro de vida",
    help: "Las primas de seguro de vida, médico y pensión privada dan deducción, hasta 120.000 yenes en total. El certificado llega por correo en otoño/invierno.",
  },
  ふるさと納税: {
    term: "ふるさと納税",
    reading: "furusato nouzei",
    es: "Donación a municipios (furusato)",
    help: "Donas a un municipio y recibes un regalo local; casi todo lo donado (menos 2.000 yenes) se deduce. Si haces 確定申告, debes declarar TODAS las donaciones aquí.",
  },
  iDeCo: {
    term: "iDeCo",
    reading: "ideko",
    es: "Pensión privada iDeCo",
    help: "Plan de pensión de aportación definida. Todo lo aportado se deduce íntegro: es de los ahorros fiscales más potentes para autónomos.",
  },
  小規模企業共済等掛金控除: {
    term: "小規模企業共済等掛金控除",
    reading: "shoukibo kigyou kyousai-tou kakekin koujo",
    es: "Deducción de aportes (iDeCo / mutua)",
    help: "Cubre los aportes a iDeCo y a la mutua de pequeñas empresas (小規模企業共済). Se deduce el importe completo aportado en el año.",
  },
  小規模企業共済: {
    term: "小規模企業共済",
    reading: "shoukibo kigyou kyousai",
    es: "Mutua de pequeñas empresas",
    help: "Una especie de plan de retiro para autónomos y dueños de pymes (gestionado por la entidad pública 中小機構). Todo lo aportado en el año se deduce íntegro del impuesto.",
  },
  損益通算: {
    term: "損益通算",
    reading: "soneki tsuusan",
    es: "Compensación de pérdidas",
    help: "Si tu negocio (事業) o un alquiler da pérdida, esa pérdida se resta de tus otros ingresos (por ejemplo tu sueldo 給与). Así baja tu base imponible y suele devolverte parte del 源泉徴収 retenido del sueldo.",
  },
  扶養控除: {
    term: "扶養控除",
    reading: "fuyou koujo",
    es: "Deducción por familiares a cargo",
    help: "Por hijos (16+) o familiares que dependen de ti económicamente. El importe varía según edad y parentesco (general 380.000, específico 630.000 yenes...). El familiar debe tener ingresos ≤ 580.000 yenes (令和7).",
  },
  老人扶養親族: {
    term: "老人扶養親族",
    reading: "roujin fuyou shinzoku",
    es: "Familiar a cargo anciano (70+)",
    help: "Familiar a cargo de 70 años o más. Si vive contigo (同居老親) deduces 580.000 yenes; si vive aparte (別居), 480.000. La edad se cuenta al 31 de diciembre.",
  },
  マイナンバー: {
    term: "マイナンバー",
    reading: "mai nanbaa",
    es: "Mi Número (12 dígitos)",
    help: "El número personal de 12 dígitos de cada residente en Japón. Hace falta declarar el de los familiares a cargo. Es un dato sensible: protégelo.",
  },
  国外居住扶養親族: {
    term: "国外居住扶養親族",
    reading: "kokugai kyojuu fuyou shinzoku",
    es: "Familiar a cargo que vive en el extranjero",
    help: "Familiar a cargo que reside fuera de Japón (p.ej. tu madre en Perú). Sigue dando deducción, pero hay que probar el vínculo y las remesas con documentos, y traducirlos al japonés. Entre 30 y 69 años solo califica con motivo (留学 / 障害者 / 送金38万円以上).",
  },
  親族関係書類: {
    term: "親族関係書類",
    reading: "shinzoku kankei shorui",
    es: "Documentos del vínculo familiar",
    help: "Prueban que el familiar en el extranjero es tu pariente: pasaporte + partida de nacimiento o registro civil (en Perú, RENIEC). Si están en español, necesitan traducción al japonés.",
  },
  送金関係書類: {
    term: "送金関係書類",
    reading: "soukin kankei shorui",
    es: "Documentos de las remesas",
    help: "Comprobantes de TODAS las transferencias de dinero del año a ese familiar (giros, extracto de tarjeta). Demuestran que lo mantienes económicamente (生計を一にする).",
  },
  配偶者控除: {
    term: "配偶者控除",
    reading: "haiguusha koujo",
    es: "Deducción por cónyuge",
    help: "Si mantienes a tu cónyuge y su ingreso es bajo, deduces hasta 380.000 yenes (480.000 si tiene 70+). Se reduce si tu propio ingreso es alto.",
  },
  仕訳: {
    term: "仕訳",
    reading: "shiwake",
    es: "Asiento contable",
    help: "El registro de una operación en la contabilidad: anota qué cuenta sube (debe) y cuál baja (haber). Cada gasto o ingreso genera un asiento.",
  },
  勘定科目: {
    term: "勘定科目",
    reading: "kanjou kamoku",
    es: "Cuenta contable",
    help: "La categoría a la que pertenece una operación (p.ej. 旅費交通費 = viajes, 消耗品費 = material). Clasifica cada gasto o ingreso.",
  },
  借方: {
    term: "借方",
    reading: "karikata",
    es: "Debe (izquierda)",
    help: "El lado izquierdo del asiento. Registra aumentos de activos/gastos. En partida doble, debe y haber siempre cuadran.",
  },
  貸方: {
    term: "貸方",
    reading: "kashikata",
    es: "Haber (derecha)",
    help: "El lado derecho del asiento. Registra aumentos de pasivos/ingresos. Su total siempre iguala al del debe.",
  },
  複式簿記: {
    term: "複式簿記",
    reading: "fukushiki boki",
    es: "Contabilidad por partida doble",
    help: "Método que anota cada operación en dos lados (debe y haber). Es obligatorio para optar a la deducción completa de la declaración azul.",
  },
  期首残高: {
    term: "期首残高",
    reading: "kishu zandaka",
    es: "Saldo de apertura",
    help: "Los saldos con los que empieza el año fiscal: caja, banco, cuentas por cobrar, deudas y capital. Deben cuadrar como activo = pasivo + capital.",
  },
  元入金: {
    term: "元入金",
    reading: "motoirekin",
    es: "Capital inicial del negocio",
    help: "El capital propio del negocio al inicio del año. En la apertura suele absorber la diferencia para que activo = pasivo + capital.",
  },
  現金: {
    term: "現金",
    reading: "genkin",
    es: "Caja / efectivo",
    help: "Dinero en efectivo del negocio al iniciar el año fiscal.",
  },
  普通預金: {
    term: "普通預金",
    reading: "futsuu yokin",
    es: "Cuenta bancaria corriente",
    help: "Saldo de la cuenta bancaria ordinaria usada por el negocio al inicio del año fiscal.",
  },
  売掛金: {
    term: "売掛金",
    reading: "urikakekin",
    es: "Cuentas por cobrar",
    help: "Facturas o trabajos ya vendidos que aún no te pagaron al inicio del año.",
  },
  買掛金: {
    term: "買掛金",
    reading: "kaikakekin",
    es: "Cuentas por pagar",
    help: "Compras o servicios recibidos que el negocio todavía debe pagar al inicio del año.",
  },
  未払金: {
    term: "未払金",
    reading: "mibaraikin",
    es: "Gastos pendientes de pago",
    help: "Importes ya devengados que todavía no se pagaron al inicio del año, distintos de compras habituales a proveedores.",
  },
  総勘定元帳: {
    term: "総勘定元帳",
    reading: "soukanjou motochou",
    es: "Libro mayor",
    help: "Reúne todos los movimientos agrupados por cada cuenta contable. Permite ver el saldo de cada categoría.",
  },
  試算表: {
    term: "試算表",
    reading: "shisanhyou",
    es: "Balance de comprobación",
    help: "Tabla que lista los saldos de todas las cuentas para verificar que debe y haber cuadran antes de cerrar el ejercicio.",
  },
  損益計算書: {
    term: "損益計算書",
    reading: "soneki keisansho",
    es: "Cuenta de resultados (P&L)",
    help: "Muestra ingresos menos gastos para llegar al beneficio del año. Es una de las dos partes del 決算書 azul.",
  },
  貸借対照表: {
    term: "貸借対照表",
    reading: "taishaku taishouhyou",
    es: "Balance de situación",
    help: "Foto del patrimonio a fin de año: activo = pasivo + capital. Necesario para la deducción azul completa de 650.000 yenes.",
  },
  課税所得: {
    term: "課税所得",
    reading: "kazei shotoku",
    es: "Base imponible",
    help: "El ingreso sobre el que se calcula el impuesto, ya restadas todas las 所得控除. Sobre esta cifra se aplican los tramos.",
  },
  所得税: {
    term: "所得税",
    reading: "shotokuzei",
    es: "Impuesto sobre la renta",
    help: "El impuesto nacional sobre tus ingresos. Es progresivo: el porcentaje sube por tramos a medida que aumenta la base imponible.",
  },
  復興特別所得税: {
    term: "復興特別所得税",
    reading: "fukkou tokubetsu shotokuzei",
    es: "Impuesto especial de reconstrucción",
    help: "Recargo del 2,1 % sobre el 所得税, destinado a la reconstrucción tras el terremoto de 2011. Vigente hasta 2037; se calcula automáticamente.",
  },
  源泉徴収: {
    term: "源泉徴収",
    reading: "gensen choushuu",
    es: "Retención en origen",
    help: "Impuesto ya retenido de tus pagos por adelantado (por clientes o el empleador). Se resta del total: si retuvieron de más, te lo devuelven.",
  },
  予定納税: {
    term: "予定納税",
    reading: "yotei nouzei",
    es: "Pago anticipado del impuesto",
    help: "Adelantos del impuesto que Hacienda exige a mitad de año si el del año anterior fue alto. Se descuentan del importe final.",
  },
  還付: {
    term: "還付",
    reading: "kanpu",
    es: "Devolución",
    help: "Cuando pagaste de más (por retenciones o anticipos), Hacienda te devuelve la diferencia. Es dinero a tu favor.",
  },
  納付: {
    term: "納付",
    reading: "noufu",
    es: "Pago (a Hacienda)",
    help: "El importe que debes ingresar a Hacienda cuando el impuesto calculado supera lo ya retenido o anticipado.",
  },
  住民税: {
    term: "住民税",
    reading: "juuminzei",
    es: "Impuesto de residencia (local)",
    help: "El impuesto local que cobra tu municipio y prefectura. NO es el 所得税 nacional: se calcula aparte (con deducciones distintas) y se paga al AÑO SIGUIENTE, normalmente de junio a mayo. No es una devolución: es un pago futuro.",
  },
  所得割: {
    term: "所得割",
    reading: "shotokuwari",
    es: "Parte proporcional (住民税)",
    help: "La parte del 住民税 que depende de tus ingresos: base imponible local × 10 % (県民税 4 % + 市民税 6 %). Es el grueso del impuesto de residencia.",
  },
  均等割: {
    term: "均等割",
    reading: "kintouwari",
    es: "Parte fija (住民税)",
    help: "Una cuota fija del 住民税, igual para casi todos sin importar el ingreso. En 津島市 (令和7): 県民税 1.500 + 市民税 3.000 + 森林環境税 1.000 = 5.500 yenes al año.",
  },
  調整控除: {
    term: "調整控除",
    reading: "chousei koujo",
    es: "Ajuste por diferencia de deducciones",
    help: "Un descuento del 住民税 que corrige que sus deducciones personales (básica, familiares...) sean menores que las del 所得税. Reduce un poco el impuesto de residencia.",
  },
  県民税: {
    term: "県民税",
    reading: "kenminzei",
    es: "Impuesto prefectural",
    help: "La parte del 住民税 que va a la prefectura (愛知県). En el 所得割 es el 4 %; en 愛知 el 均等割 incluye la あいち森と緑づくり税 (500 yenes).",
  },
  市民税: {
    term: "市民税",
    reading: "shiminzei",
    es: "Impuesto municipal",
    help: "La parte del 住民税 que va a tu municipio (津島市). En el 所得割 es el 6 %, la mayor parte del impuesto de residencia.",
  },
  森林環境税: {
    term: "森林環境税",
    reading: "shinrin kankyouzei",
    es: "Impuesto forestal nacional",
    help: "Tributo nacional de 1.000 yenes al año (desde 令和6/2024) que se cobra junto al 均等割 del 住民税. Financia la gestión de bosques. Lo recauda el municipio.",
  },
  経費: {
    term: "経費",
    reading: "keihi",
    es: "Gastos del negocio",
    help: "Gastos necesarios para tu actividad (material, viajes, comunicaciones...). Se restan de las ventas y reducen el beneficio gravable.",
  },
  売上: {
    term: "売上",
    reading: "uriage",
    es: "Ventas / ingresos",
    help: "Los ingresos brutos de tu actividad antes de restar gastos. Base del cálculo del beneficio del negocio.",
  },
  事業所得: {
    term: "事業所得",
    reading: "jigyou shotoku",
    es: "Rendimiento de actividad",
    help: "El beneficio de tu negocio: ventas menos gastos (y menos la deducción especial azul). Es el núcleo de la declaración de un autónomo.",
  },
  給与所得: {
    term: "給与所得",
    reading: "kyuuyo shotoku",
    es: "Rendimiento del trabajo",
    help: "Ingresos por salario/nómina, tras una deducción estándar por trabajo. Si solo tienes esto, normalmente no hace falta declarar.",
  },
  雑所得: {
    term: "雑所得",
    reading: "zatsu shotoku",
    es: "Otros ingresos (varios)",
    help: "Ingresos que no encajan en otras categorías (pequeñas ventas online, pensiones, cripto...). Tienen sus propias reglas de cálculo.",
  },
  消費税: {
    term: "消費税",
    reading: "shouhizei",
    es: "IVA japonés",
    help: "Impuesto al consumo (10 % general). Solo lo declaran e ingresan los negocios obligados (p.ej. con ventas altas o inscritos como インボイス).",
  },
  軽減税率: {
    term: "軽減税率",
    reading: "keigen zeiritsu",
    es: "Tipo reducido del IVA",
    help: "Tipo del 8 % para alimentos y bebidas (no alcohólicas) y ciertos periódicos, frente al 10 % general.",
  },
  適格請求書: {
    term: "適格請求書",
    reading: "tekikaku seikyuusho",
    es: "Factura calificada (invoice)",
    help: "Factura del sistema インボイス que incluye el número de registro del emisor. Es necesaria para que el cliente deduzca el IVA soportado.",
  },
  インボイス: {
    term: "インボイス",
    reading: "inboisu",
    es: "Sistema de facturas (invoice)",
    help: "Régimen de facturación del IVA vigente desde octubre de 2023. Para deducir IVA, las facturas deben llevar el número de registro del emisor.",
  },
  登録番号: {
    term: "登録番号",
    reading: "touroku bangou",
    es: "Número de registro (invoice)",
    help: "Código (T + 13 dígitos) que identifica al emisor inscrito en el sistema インボイス. Debe figurar en las facturas calificadas.",
  },
  課税事業者: {
    term: "課税事業者",
    reading: "kazei jigyousha",
    es: "Sujeto pasivo del IVA",
    help: "Negocio obligado a declarar e ingresar el 消費税. Lo es quien tuvo ventas gravadas superiores a 10 millones de yenes en el periodo base (前々年), o quien se inscribió voluntariamente como インボイス.",
  },
  免税事業者: {
    term: "免税事業者",
    reading: "menzei jigyousha",
    es: "Exento de IVA",
    help: "Negocio NO obligado a declarar 消費税 (ventas del periodo base ≤ 10 millones de yenes y sin inscripción インボイス). No presenta la declaración del impuesto al consumo.",
  },
  売上税額: {
    term: "売上税額",
    reading: "uriage zeigaku",
    es: "IVA repercutido (ventas)",
    help: "El 消費税 contenido en tus ventas. Se separa por tipo: 10% general y 8% reducido (区分経理). Es el punto de partida del cálculo del impuesto a ingresar.",
  },
  仕入税額控除: {
    term: "仕入税額控除",
    reading: "shiire zeigaku koujo",
    es: "IVA soportado deducible (compras)",
    help: "El 消費税 de tus compras/gastos que puedes restar del repercutido. En el régimen インボイス solo es deducible si el gasto tiene factura calificada (適格請求書).",
  },
  本則課税: {
    term: "本則課税",
    reading: "honsoku kazei",
    es: "Régimen general del IVA",
    help: "Método estándar: impuesto a pagar = IVA de ventas − IVA real de compras (solo con factura calificada). El más preciso, pero exige llevar el detalle de cada gasto.",
  },
  簡易課税: {
    term: "簡易課税",
    reading: "kani kazei",
    es: "Régimen simplificado del IVA",
    help: "En vez del IVA real de compras, deduce un porcentaje fijo (みなし仕入率) según tu tipo de negocio (40-90%). Disponible si las ventas base ≤ 50 millones de yenes.",
  },
  "2割特例": {
    term: "2割特例",
    reading: "ni-wari tokurei",
    es: "Régimen especial del 20%",
    help: "Medida transitoria para quien pasó de exento a sujeto por la インボイス: solo ingresa el 20% del IVA de ventas. Vigente hasta el 30/09/2026; luego pasa al especial del 30% (3割特例) solo para autónomos.",
  },
  みなし仕入率: {
    term: "みなし仕入率",
    reading: "minashi shiiremiritsu",
    es: "Porcentaje fijo de compras",
    help: "El porcentaje del IVA de ventas que el régimen simplificado considera como IVA de compras, según el tipo de actividad: mayorista 90%, minorista 80%, fabricación 70%, otros 60%, servicios 50%, inmobiliario 40%.",
  },
  事業区分: {
    term: "事業区分",
    reading: "jigyou kubun",
    es: "Categoría de actividad (IVA)",
    help: "La clasificación de tu negocio (1ª a 6ª categoría) que fija la みなし仕入率 del régimen simplificado. Por ejemplo, un freelance de servicios es 5ª categoría (50%).",
  },
  納付税額: {
    term: "納付税額",
    reading: "noufu zeigaku",
    es: "Impuesto a ingresar",
    help: "El 消費税 final que debes pagar: IVA de ventas − IVA deducible, más el tramo local (地方消費税). Es lo que efectivamente se ingresa a Hacienda.",
  },
  決算書: {
    term: "決算書",
    reading: "kessansho",
    es: "Cuentas anuales",
    help: "Los estados financieros del año. En la azul incluye cuenta de resultados y balance de situación; se adjunta a la declaración.",
  },
  収支内訳書: {
    term: "収支内訳書",
    reading: "shuushi uchiwakesho",
    es: "Desglose de ingresos y gastos",
    help: "Documento simplificado de ingresos y gastos que acompaña a la declaración blanca (equivalente sencillo del 決算書 azul).",
  },
  確定申告書: {
    term: "確定申告書",
    reading: "kakutei shinkokusho",
    es: "Formulario de la declaración",
    help: "El impreso oficial (Tabla 1 y Tabla 2) donde se anotan ingresos, deducciones e impuesto. Es el documento principal que se presenta.",
  },
  帳簿: {
    term: "帳簿",
    reading: "choubo",
    es: "Libros contables",
    help: "Los registros de tus operaciones (diario, mayor...). La ley exige conservarlos; en la azul son obligatorios y formales.",
  },
  領収書: {
    term: "領収書",
    reading: "ryoushuusho",
    es: "Recibo (justificante)",
    help: "Comprobante formal de un pago, con emisor y fecha. Respalda los gastos; conviene guardarlos por si Hacienda los pide.",
  },
  レシート: {
    term: "レシート",
    reading: "reshiito",
    es: "Tique de caja",
    help: "El tique impreso de una compra. También sirve como justificante de gasto aunque sea menos formal que un 領収書.",
  },
  取引先: {
    term: "取引先",
    reading: "torihikisaki",
    es: "Cliente / proveedor",
    help: "La contraparte de una operación: a quién le vendes o de quién compras. Se identifica en cada asiento y factura.",
  },
  税抜: {
    term: "税抜",
    reading: "zeinuki",
    es: "Sin IVA",
    help: "El importe SIN el impuesto al consumo incluido. El IVA se añade aparte para llegar al precio final.",
  },
  税込: {
    term: "税込",
    reading: "zeikomi",
    es: "Con IVA incluido",
    help: "El importe que YA incluye el impuesto al consumo. Es el precio total que efectivamente se paga.",
  },
  青色申告特別控除: {
    term: "青色申告特別控除",
    reading: "aoiro shinkoku tokubetsu koujo",
    es: "Deducción especial azul",
    help: "Beneficio estrella de la declaración azul: hasta 650.000 yenes de deducción si llevas partida doble y presentas por e-Tax (550.000 en papel; 100.000 en modo simple).",
  },
  家計簿: {
    term: "家計簿",
    reading: "kakeibo",
    es: "Libro de gastos personales",
    help: "Cuaderno doméstico para anotar los gastos personales del día a día. NO entra en la declaración: sirve para controlar el presupuesto del hogar, separado de los gastos del negocio.",
  },
  費目: {
    term: "費目",
    reading: "himoku",
    es: "Categoría de gasto",
    help: "La categoría a la que pertenece un gasto del hogar (comida, transporte, ocio…). En el 家計簿 se usa para ver en qué se va el dinero cada mes.",
  },
};

/**
 * Resuelve un termino tolerando variantes comunes que aparecen en las
 * etiquetas de la UI (sufijos como 額/金/控除 sueltos, barras "/", parentesis).
 * Devuelve la entrada del glosario o `undefined` si no hay match.
 *
 * @param raw - Texto del termino tal como aparece en la UI.
 * @returns La entrada del glosario, o `undefined` si no esta cubierto.
 */
export function lookupTerm(raw: string): GlossaryEntry | undefined {
  const key = raw.trim();
  if (GLOSSARY[key]) return GLOSSARY[key];

  // Variantes con barra (適格請求書/インボイス) -> probar cada lado.
  for (const part of key.split(/[／/]/)) {
    const p = part.trim();
    if (GLOSSARY[p]) return GLOSSARY[p];
  }

  // Sufijos sueltos que la UI suele anadir (額, 金, の合計...).
  const stripped = key.replace(/(の合計|合計|額|金|分)$/u, "");
  if (stripped !== key && GLOSSARY[stripped]) return GLOSSARY[stripped];

  return undefined;
}

/** Numero de terminos cubiertos (para inventario/tests). */
export const GLOSSARY_SIZE = Object.keys(GLOSSARY).length;
