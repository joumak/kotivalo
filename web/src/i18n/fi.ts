import type { Messages } from './en'

const ago = (minutes: number) =>
  minutes < 1
    ? 'juuri nyt'
    : minutes < 60
      ? `${minutes} min sitten`
      : minutes < 48 * 60
        ? `${Math.round(minutes / 60)} h sitten`
        : `${Math.round(minutes / 1440)} päivää sitten`

const inTime = (minutes: number) => {
  if (minutes < 1) return 'nyt'
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  if (h === 0) return `${m} min päästä`
  if (h < 48) return `${h} h ${m} min päästä`
  return `${Math.round(h / 24)} päivän päästä`
}

export const fi: Messages = {
  locale: 'fi-FI',
  nav: { lights: 'Valot', wakeup: 'Herätys', devices: 'Laitteet', settings: 'Asetukset' },
  banner: {
    offline: 'Ei yhteyttä Kotivaloon. Yritetään uudelleen…',
    unauthorized: 'Tämä sivu tarvitsee pääsykoodin. Anna se asetuksissa.',
    clock: 'Kelloa ei ole vielä täsmätty, joten herätykset käyttävät laitteen omaa kelloa.',
  },
  time: { ago, inTime },
  lamp: {
    off: 'Pois',
    level: (percent) => `${percent} %`,
    kelvin: (kelvin) => `${Math.round(kelvin / 50) * 50} K`,
    brightness: 'Kirkkaus',
    warmth: 'Sävy',
    warm: 'Lämmin',
    cool: 'Viileä',
    notResponding: 'Ei vastaa',
    turnOn: (name) => `Sytytä ${name}`,
    turnOff: (name) => `Sammuta ${name}`,
    sunrise: (time) => `Auringonnousu, täysi klo ${time}`,
    sunriseHold: (time) => `Herätys valmis, sammuu klo ${time}`,
    sunriseDone: 'Herätys valmis',
    motionOn: 'Liikkeestä päällä',
    nightLight: 'Yövalo',
    offAt: (status, time) => `${status}, sammuu klo ${time}`,
    wakeupLamp: 'Herätysvalo',
    noRoom: 'Muut valot',
    noLamps: 'Ei vielä valoja. Lisää valo Laitteet-sivulla.',
    pickOne: 'Valitse säädettävä valo.',
  },
  wakeup: {
    noAlarm: 'Ei herätyksiä. Valitse päivät alta.',
    when: (weekday, relative) => `${weekday}, ${relative}`,
    lightStarts: (time) => `Valo syttyy klo ${time}`,
    offAt: (time) => `sammuu klo ${time}`,
    staysOn: 'jää päälle',
    skip: 'Ohita tämä',
    unskip: 'Älä ohita',
    skipped: 'Ohitettu',
    later: 'Sen jälkeen',
    days: 'Herätyspäivät',
    dayOff: 'Ei',
    editTitle: (weekday) => `Herätys: ${weekday}`,
    enabled: 'Herätys tänä päivänä',
    time: 'Kellonaika',
    save: 'Tallenna',
    cancel: 'Peruuta',
    sunrise: 'Auringonnousu',
    duration: 'Kirkastuu',
    minutes: (n) => `${n} min`,
    switchOff: 'Sammuu',
    never: 'Ei koskaan',
    after: (n) => `${n} min kuluttua`,
    startWarmth: 'Alkusävy',
    endWarmth: 'Loppusävy',
    curve: 'Kirkastuminen',
    curveEven: 'Tasainen',
    curveSlow: 'Pitkään himmeä',
    saveSunrise: 'Tallenna',
    saved: 'Tallennettu',
    lamp: 'Herätysvalo',
    noLamp: 'Valitse herätysvalo',
    tryIt: 'Kokeile',
    running: 'Auringonnousu käynnissä',
    testRunning: 'Kokeilu käynnissä',
    fullAt: (time) => `Täysi kirkkaus klo ${time}`,
    stop: 'Lopeta',
    lastAlarm: (result, time) => `Edellinen herätys ${result} klo ${time}.`,
    result: { completed: 'onnistui', cancelled: 'keskeytettiin', failed: 'epäonnistui' },
  },
  sensor: {
    occupied: 'Liikettä',
    empty: 'Ei liikettä',
    lux: (lux) => `${lux < 10 ? lux.toFixed(1).replace('.', ',') : Math.round(lux)} lx`,
    battery: (percent) => `Paristo ${Math.round(percent)} %`,
    settings: (name) => `${name}: liikevalot`,
    enabled: 'Liike sytyttää valot',
    lamps: 'Valot, jotka se sytyttää',
    takenBy: (name) => `Jo tunnistimen ${name} ohjaama`,
    darkerThan: 'Vain kun pimeämpää kuin',
    always: 'Aina, myös päivänvalossa',
    luxNow: (lux) => `Nyt ${lux}`,
    offAfter: 'Sammuu, kun huone on ollut tyhjänä',
    minutes: (n) => `${n} min`,
    day: 'Päivällä',
    night: 'Yöllä',
    nightHint: (from, to) => `Yö on ${from}–${to}, asetetaan Asetuksissa.`,
    brightness: 'Kirkkaus',
    warmth: 'Sävy',
    save: 'Tallenna',
    notConfigured: 'Asetetaan: liiku tunnistimen edessä, niin se herää.',
  },
  devices: {
    kinds: { light: 'Valot', motion: 'Liiketunnistimet', remote: 'Kaukosäätimet', other: 'Muut laitteet' },
    add: 'Lisää laite',
    addTitle: 'Lisää laite',
    addWhat: 'Mitä olet lisäämässä?',
    addLamp: 'IKEA-valon',
    addSensor: 'Liiketunnistimen (VALLHORN)',
    startPairing: 'Aloita liittäminen',
    close: 'Sulje',
    sensorHelp:
      'Paina tunnistimen liitospainiketta 4 kertaa nopeasti, 5 sekunnin sisällä. Punainen valo vilkkuu ja sammuu, kun tunnistin on liitetty. Pidä se liittämisen ajan lähellä valoa.',
    sensorBatteries:
      'Käytä ladattavia paristoja (IKEA LADDA). Tavalliset 1,5 V:n paristot saavat tunnistimen näkemään liikettä, jota ei ole.',
    pairing: (seconds) => `Liittäminen auki, ${seconds} s jäljellä`,
    stopPairing: 'Lopeta liittäminen',
    pairHelp:
      'Kun valo on päällä, sammuta ja sytytä se 6 kertaa noin sekunnin välein ja jätä se päälle. Valo välähtää, kun se liittyy.',
    rename: 'Nimeä',
    name: 'Nimi',
    room: 'Huone',
    roomHint: 'Esimerkiksi Makuuhuone',
    remove: 'Poista',
    removeTitle: (name) => `Poistetaanko ${name}?`,
    removeBody: 'Laite poistuu Zigbee-verkosta. Jotta voit käyttää sitä taas, liitä se uudelleen.',
    useForWakeup: 'Käytä herätykseen',
    seen: (relative) => `Nähty ${relative}`,
    notSeen: 'Ei liitetty',
    empty: 'Ei vielä laitteita.',
  },
  settings: {
    language: 'Kieli',
    panel: 'Tämä näyttö on seinäpaneeli',
    panelHelp: 'Näyttää ison kellon ja valot, ja tummuu yöksi.',
    night: 'Yö',
    nightHelp: 'Liike sytyttää vain himmeän yövalon, ja paneeli tummuu. Yö päättyy aiemmin, jos herätys alkaa.',
    from: 'Alkaa',
    to: 'Päättyy',
    saveNight: 'Tallenna',
    token: 'Pääsykoodi',
    tokenHelp: 'Tarvitaan vain, jos laitteeseen on asetettu koodi.',
    saveToken: 'Käytä tätä koodia',
    saved: 'Tallennettu',
  },
  panel: {
    menu: 'Valikko',
    back: 'Takaisin paneeliin',
    alarm: (weekday, time) => `Herätys ${weekday} ${time}`,
    noAlarm: 'Ei herätystä',
    tapToWake: 'Näytä valot napauttamalla',
  },
  error: {
    lamp: 'Valo ei vastannut. Tarkista, että sen virta on päällä.',
    unreachable: 'Ei yhteyttä Kotivaloon.',
    generic: (message) => `Ei onnistunut: ${message}`,
  },
}
